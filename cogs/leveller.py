import discord
from discord.ext import commands
from discord import Member, Status, User, Reaction, Message

from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from pymongo import ReturnDocument

from datetime import datetime, timedelta, timezone

import os
import dotenv

class Leveller(commands.Cog):
  def __init__(self, bot, mongo: MongoClient):
    self.bot = bot
    self.users = mongo.database.users
    self.vc = mongo.database.vc
    self.admin = mongo.database.admin
    self.roles = [(1, 1134948712980947024), (2, 1184378443249504276), (3, 1267953974791766076), (4, 1190584957895200878)]

  @commands.Cog.listener()
  async def on_ready(self):
    self.guild = await self.bot.fetch_guild(int(os.environ["OPERATING_GUILD"])) 
    self.vc.delete_many({})
    for channel in self.guild.channels:
      if not isinstance(channel, discord.VoiceChannel):
        continue
      await self.refresh_channel(channel)
    await self.update_database()

  @commands.Cog.listener()
  async def on_message(self, message):
    if message.author.bot:
      return
    if message.content:
      if message.content.startswith(self.bot.command_prefix):
        return
    elif not message.attachments:
      return

    now = datetime.now(timezone.utc)
    doc = self.users.find_one({"_id": message.author.id})
    if not doc:
      self.users.insert_one({"_id": message.author.id, "last_msg_date": now})
      return

    if doc.get("last_msg_date"):
      if now - doc.get("last_msg_date") < timedelta(seconds=15):
        return

    self.users.update_one(
      {"_id": message.author.id},
      {"$set": {"last_msg_date": now}},
      upsert=True
    )

    amount = await self.calculate(message)
    await self.award(message.author.id, amount, "text")

  @commands.command()
  async def award(self, recipient: int, amount: int = 0, type: str = "text"):
    doc = self.users.find_one({"_id": recipient})

    if type == "text":
      new_doc = self.users.find_one_and_update(
        {"_id": recipient},
        {"$set": {"text": (doc.get("text", 0) + amount)}},
        upsert=True,
        return_document=ReturnDocument.AFTER
      )
    if type == "voice":
      new_doc = self.users.find_one_and_update(
        {"_id": recipient},
        {"$set": {"voice": (doc.get("voice", 0) + amount)}},
        upsert=True,
        return_document=ReturnDocument.AFTER
      )

    await self.check(new_doc)

  async def calculate(self, message: discord.Message = None, timedelta: timedelta = None):
    if message:
      return self.TEXT_AWARD
    if timedelta:
      return (self.VOICE_AWARD * (timedelta // 60))

  async def check(self, doc):
    user = await self.guild.fetch_member(doc["_id"])
    total_exp = doc.get("text", 0) + doc.get("voice", 0)

    level = 0
    cutoff_exp = 0
    while cutoff_exp < total_exp:
      cutoff_exp = 5 * level**2 + 50 * level + 100
      level += 1
    current_level = level - 1

    prev_level = doc.get("level")
    if prev_level != current_level:
      self.collection.update_one({"_id": doc["_id"]}, {"$set": {"level": current_level}})
      if prev_level is not None and current_level > prev_level:
        try:
          await user.send(f"Congratulations **{user.nick}**, you just advanced to **level {current_level}**!")
        except discord.Forbidden:
          pass

    user_role_list = [role.id for role in user.roles]
    for threshold, role_id in self.roles:
      if current_level >= threshold and role_id not in user_role_list:
        role = self.guild.get_role(role_id)
        if not role:
          role = await self.guild.fetch_role(role_id)
        await user.add_roles(role)

  async def update_database():
    self.TIME_INCREMENT = self.admin.config.find_one({"_id": "time_increment"}).get("value", 15)
    self.TEXT_AWARD = self.admin.config.find_one({"_id": "text_award"}).get("value", 4.5)
    self.VOICE_AWARD = self.admin.config.find_one({"_id": "voice_award"}).get("value", 6)
    self.VC_CONCURRENT_MEMBERS = self.admin.config.find_one({"_id": "vc_concurrent_members"}).get("value", 2)

# ****************
# ****************
# **** VOICE *****
# ****************
# ****************

  async def start_segment(self, member_id):
    self.vc.update_one(
      {"_id": member_id},
      {"$setOnInsert": {"joined": datetime.now(timezone.utc)}},
      upsert=True,
    )

  async def end_segment(self, member_id):
    doc = self.vc.find_one_and_delete({"_id": member_id})
    if doc:
      await self.award(member_id, calculate(timedelta=(datetime.now(timezone.utc) - doc["joined"])), "voice")

  async def refresh_channel(self, channel):
    members = [m for m in channel.members if not m.bot]
    big_enough = len(members) >= self.VC_CONCURRENT_MEMBERS
    for m in members:
      deaf = m.voice.self_deaf or m.voice.deaf
      if big_enough and not deaf:
        await self.start_segment(m.id)
      else:
        await self.end_segment(m.id)

  @commands.Cog.listener()
  async def on_voice_state_update(self, member, before, after):
    changed_channel = before.channel != after.channel
    changed_inactive = before.self_deaf != after.self_deaf or before.deaf != after.deaf
    if not (changed_channel or changed_inactive):
      return
    if changed_channel:
      await self.end_segment(member.id)
    for ch in (before.channel, after.channel):
      if ch is not None:
        await self.refresh_channel(ch)
