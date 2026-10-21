import discord
from discord.ext import commands, tasks
from discord import Member, Status, User, Reaction, Message, Embed

from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from pymongo import ReturnDocument

from datetime import datetime, timedelta, timezone

import os
import dotenv

class Voice(commands.Cog):
  def __init__(self, bot, mongo: MongoClient):
    self.bot = bot
    self.users = mongo.database.users
    self.vc = mongo.database.vc
    self.recent = mongo.database.recent
    self.config = mongo.database.config
    self.update_database()

  @commands.Cog.listener()
  async def on_ready(self):
    self.guild = await self.bot.fetch_guild(int(os.environ["OPERATING_GUILD"])) 
    self.vc.delete_many({})
    for channel in self.guild.channels:
      if not isinstance(channel, discord.VoiceChannel):
        continue
      await self.refresh_channel(channel)
    self.update_database()

  def update_database(self):
    self.VOICE_AWARD = int((self.config.find_one({"setting": "voice_award"}))["value"].get("value", 6))
    self.VC_CONCURRENT_MEMBERS = int((self.config.find_one({"setting": "vc_concurrent_members"}))["value"].get("value", 2))
    self.roles = [(int(doc["value"]["threshold"]),int(doc["value"]["role_id"]),doc["value"]["message"]) for doc in self.config.find({"setting": {"$regex": "^reward_"}})]
    self.roles.sort(key=lambda t: t[0])
    self.immune_roles = self.config.find_one({"setting": "immune_roles"})["value"]["list"]
    self.VC_DAILY_CAP = int((self.config.find_one({"setting": "vc_daily_cap"}))["value"].get("hours", 2))
    self.VC_WINDOW = int((self.config.find_one({"setting": "vc_window"}))["value"].get("hours", 16))
    debug = (self.config.find_one({"setting": "debug"}))["value"]
    self.DEBUG = [debug.get("enabled", "True") == "True", int(debug.get("category_id", 0))]




  async def start_segment(self, member_id):
    self.vc.update_one(
      {"_id": member_id},
      {"$setOnInsert": {"joined": datetime.now(timezone.utc)}},
      upsert=True,
    )

  async def end_segment(self, member_id):
    doc = self.vc.find_one_and_delete({"_id": member_id})
    if doc:
      duration = datetime.now(timezone.utc) - doc["joined"]
      granted = self.apply_daily_cap(member_id, doc["joined"], duration)
      if granted > timedelta(0):
        await self.internal_award(member_id, self.calculate(timedelta=granted), "voice")

  def apply_daily_cap(self, member_id, joined, duration):
    now = datetime.now(timezone.utc)
    doc = self.users.find_one({"_id": member_id}) or {}
    window_start = doc.get("vc_window_start")
    used = doc.get("vc_window_seconds", 0)

    if window_start is None or now - window_start >= timedelta(hours=self.VC_WINDOW):
      window_start, used = now, 0

    allowed = max(0, timedelta(hours=self.VC_DAILY_CAP).total_seconds() - used)
    granted = min(duration.total_seconds(), allowed)

    self.users.update_one(
      {"_id": member_id},
      {"$set": {
        "vc_window_start": window_start,
        "vc_window_seconds": used + granted,
      }},
      upsert=True,
    )

    return timedelta(seconds=granted)

  async def refresh_channel(self, channel):
    members = [m for m in channel.members if not m.bot]
    big_enough = len(members) >= self.VC_CONCURRENT_MEMBERS
    for m in members:
      deaf = m.voice.self_deaf or m.voice.deaf
      skip = any(a.id in self.immune_roles for a in m.roles)
      if big_enough and not deaf and not skip:
        await self.start_segment(m.id)
      else:
        await self.end_segment(m.id)

  @commands.Cog.listener()
  async def on_voice_state_update(self, member, before, after):
    if self.DEBUG[0]:
      channel = after.channel or before.channel
      if not channel.category_id == self.DEBUG[1]:
        return
    changed_channel = before.channel != after.channel
    changed_inactive = before.self_deaf != after.self_deaf or before.deaf != after.deaf
    if not (changed_channel or changed_inactive):
      return
    if changed_channel:
      await self.end_segment(member.id)
    for ch in (before.channel, after.channel):
      if ch is not None:
        await self.refresh_channel(ch)

# this is just here in the small chance that the bot misses an API event related to VCs for any reason
  @tasks.loop(minutes=10)
  async def double_check(self):
    active = set()
    for channel in self.guild.voice_channels:
      if self.DEBUG[0] and channel.category_id != self.DEBUG[1]:
        continue
      await self.refresh_channel(channel)
      members = [m for m in channel.members if not m.bot]
      if len(members) >= self.VC_CONCURRENT_MEMBERS:
        active.update(m.id for m in members if not (m.voice.self_deaf or m.voice.deaf))
    for doc in list(self.vc.find({"_id": {"$nin": list(active)}})):
      await self.end_segment(doc["_id"])

  @double_check.before_loop
  async def before_double_check(self):
    await self.bot.wait_until_ready()

  async def internal_award(self, recipient: int = 0, amount: int = 0, type: str = "text"):
    if recipient == 0 or type not in ["text", "voice"]:
      return

    new_doc = self.users.find_one_and_update(
      {"_id": recipient},
      {"$inc": {type: amount}},
      upsert=True,
      return_document=ReturnDocument.AFTER
    )

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    self.recent.update_one(
      {"user": recipient, "date": today},
      {"$inc": {type: amount}},
      upsert=True
    )

    if new_doc:
      await self.check(new_doc)

  def calculate(self, timedelta: timedelta = None):
    # put whatever calculations you want here!
    return (self.VOICE_AWARD * (timedelta.total_seconds() // 60))

  async def check(self, doc):
    user = await self.guild.fetch_member(doc["_id"])
    total_exp = doc.get("text", 0) + doc.get("voice", 0)

    level = 0
    needed_exp = 100
    while total_exp >= needed_exp:
      level += 1
      needed_exp += 5 * level**2 + 50 * level + 100
    current_level = level

    prev_level = doc.get("level")
    if prev_level != current_level:
      self.users.update_one({"_id": doc["_id"]}, {"$set": {"level": current_level}})
      if prev_level is not None and current_level > prev_level:
        try:
          await user.send(f"Congratulations **{user.nick or user.display_name}**, you just advanced to **level {current_level}**!")
        except discord.Forbidden:
          pass

    user_role_list = [role.id for role in user.roles]
    for threshold, role_id, message in self.roles:
      if current_level >= threshold and role_id not in user_role_list:
        role = self.guild.get_role(role_id)
        if not role:
          role = await self.guild.fetch_role(role_id)
        await user.add_roles(role)
        await user.send(message.strip("\""))

