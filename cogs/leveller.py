import discord
from discord.ext import commands
from discord import Member, Status, User, Reaction, Message, Embed

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
    self.config = mongo.database.config

  @commands.Cog.listener()
  async def on_ready(self):
    self.guild = await self.bot.fetch_guild(int(os.environ["OPERATING_GUILD"])) 
    self.vc.delete_many({})
    for channel in self.guild.channels:
      if not isinstance(channel, discord.VoiceChannel):
        continue
      await self.refresh_channel(channel)
    await self.update_database()

  async def update_database(self):
    self.TIME_INCREMENT = int((self.config.find_one({"setting": "time_increment"}))["value"].get("value", 10))
    self.TEXT_AWARD = int((self.config.find_one({"setting": "text_award"}))["value"].get("value", 3))
    self.VOICE_AWARD = int((self.config.find_one({"setting": "voice_award"}))["value"].get("value", 6))
    self.VC_CONCURRENT_MEMBERS = int((self.config.find_one({"setting": "vc_concurrent_members"}))["value"].get("value", 2))
    self.roles = [(int(doc["value"]["threshold"]),int(doc["value"]["role_id"]),doc["value"]["message"]) for doc in self.config.find({"setting": {"$regex": "^reward_"}})]
    self.roles.sort(key=lambda t: t[0])
    self.immune_roles = self.config.find_one({"setting": "immune_roles"})["value"]["list"]


  @commands.Cog.listener()
  async def on_message(self, message):
    if message.author.bot:
      return
    if message.content:
      if message.content.startswith(self.bot.command_prefix):
        return
    elif not message.attachments:
      return
    if any(a.id in self.immune_roles for a in message.author.roles):
      return

    now = datetime.now(timezone.utc)
    doc = self.users.find_one({"_id": message.author.id})
    if not doc:
      self.users.insert_one({"_id": message.author.id, "last_msg_date": now})
      return

    if doc.get("last_msg_date"):
      if now - doc.get("last_msg_date") < timedelta(seconds=self.TIME_INCREMENT):
        return

    self.users.update_one(
      {"_id": message.author.id},
      {"$set": {"last_msg_date": now}},
      upsert=True
    )

    amount = await self.calculate(message)
    await self.internal_award(recipient=message.author.id, amount=amount, type="text")


# -----------------
# -----------------
# --- INTERNALS ---
# -----------------
# -----------------

  async def internal_award(self, recipient: int = 0, amount: int = 0, type: str = "text"):
    if recipient == 0:
      return
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
      self.users.update_one({"_id": doc["_id"]}, {"$set": {"level": current_level}})
      if prev_level is not None and current_level > prev_level:
        try:
          await user.send(f"Congratulations **{user.nick}**, you just advanced to **level {current_level}**!")
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

  def exp_for_level(self, level):
    if level <= 0:
      return 0
    prev = level - 1
    return 5 * prev**2 + 50 * prev + 100 + 1

# ------------------
# ------------------
# ---- COMMANDS ----
# ------------------
# ------------------

  @commands.command()
  async def level(self, ctx: commands.Context, option: int|User|Member|str = 0):
    if  option == "up":
      doc = self.users.find_one({"_id": ctx.author.id})
      if doc:
        await self.check(doc)
        await ctx.send("Successfully counted every last experience point and awarded you with the associated roles.")
      return

    if option == 0:
      id = ctx.author.id
    elif isinstance(option, User) or isinstance(option, Member):
      id = option.id
    else:
      id = option

    try:
      user = await self.guild.fetch_member(id)
    except discord.NotFound:
      user = None
    except discord.HTTPException:
      user = None

    if not id or not user:
      await ctx.send(f"I have thoroughly checked every tome and scroll in my library and found none for this `{option}` person!")
      return

    doc = self.users.find_one({"_id": id})
    if not doc:
      await ctx.send(f"I have thoroughly checked every tome and scroll in my library and found none for this `{option}` person!")
      return

    current_level = doc.get("level", 0)
    current_exp = doc.get("text", 0) + doc.get("voice", 0)
    embed = Embed(title=f'Counting EXP for {user.nick}', color=user.accent_color)
    embed.add_field(name='Text EXP', value=doc.get("text", 0), inline=True)
    embed.add_field(name='Voice EXP', value=doc.get("voice", 0), inline=True)
    embed.add_field(name='Total EXP', value=current_exp, inline=True)
    embed.add_field(name='Level', value=current_level, inline=True)

    old_exp = self.exp_for_level(doc.get("level", 0))
    next_exp = self.exp_for_level(1 + doc.get("level", 0)) - old_exp
    progress = (current_exp - old_exp) / next_exp * 100
    embed.add_field(name='Progress', value=f'{current_exp - old_exp} / {next_exp} ({progress:.1f}%)', inline=True)
    embed.add_field(name='Next Role', value=next((f'<@&{r}>' for t, r, m in self.roles if t > current_level), 'None!'), inline=True)

    embed.set_footer(text="TIP: Commands do not grant experience points.")
    await ctx.send(embed=embed)



  @commands.command()
  async def leaderboard(self, ctx, range: str = "10"):
    low, sep, high = range.partition("-")
    try:
      if sep:
        start, finish = int(low), int(high)
      else:
        start, finish = 1, int(low)
    except ValueError:
      await ctx.send("Usage: `!leaderboard 10` or `!leaderboard 50-100`")
      return

    if start < 1 or finish <= start or finish - start + 1 > 50:
      await ctx.send(f"You cannot possibly expect me to count through such a range. Range must be valid (e.g. `10-25` and at most FIFTY results at a time. No more!")
      return

    skip = start - 1
    limit = finish - start + 1
    pipeline = [
      {"$addFields": {
        "total_exp": {"$add": [
          {"$ifNull": ["$text", 0]},
          {"$ifNull": ["$voice", 0]},
        ]}
      }},
      {"$sort": {"total_exp": -1}},
      {"$skip": skip},
      {"$limit": limit},
    ]

    description = "\n".join(
      f'{rank}. <@{doc["_id"]}>: Level `{doc.get("level", 0)}` '
      f'w/ **{doc.get("text", 0) + doc.get("voice", 0)}** Total EXP '
      f'(**{doc.get("text", 0)}** Text / **{doc.get("voice", 0)}** Voice)'
      for rank, doc in enumerate(self.users.aggregate(pipeline), start=start)
    )
    embed = Embed(title="Leaderboard", description=description, color=0xA9BFBE)
    await ctx.send(embed=embed)


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
      await self.internal_award(member_id, calculate(timedelta=(datetime.now(timezone.utc) - doc["joined"])), "voice")

  async def refresh_channel(self, channel):
    members = [m for m in channel.members if not m.bot]
    big_enough = len(members) >= self.VC_CONCURRENT_MEMBERS
    for m in members:
      deaf = m.voice.self_deaf or m.voice.deaf
      skip = any(a.id in self.immune_roles for a in message.author.roles)
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
