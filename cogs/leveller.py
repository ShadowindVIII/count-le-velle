import discord
from discord.ext import commands
from discord import Member, Status, User, Reaction, Message, Embed

from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from pymongo import ReturnDocument

from datetime import datetime, timedelta, timezone

import os
import dotenv
COMMAND_COOLDOWN = os.environ['COMMAND_COOLDOWN']

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
    self.update_database()

  def update_database(self):
    self.TIME_INCREMENT = int((self.config.find_one({"setting": "time_increment"}))["value"].get("value", 10))
    self.TEXT_AWARD = int((self.config.find_one({"setting": "text_award"}))["value"].get("value", 3))
    self.VOICE_AWARD = int((self.config.find_one({"setting": "voice_award"}))["value"].get("value", 6))
    self.VC_CONCURRENT_MEMBERS = int((self.config.find_one({"setting": "vc_concurrent_members"}))["value"].get("value", 2))
    self.roles = [(int(doc["value"]["threshold"]),int(doc["value"]["role_id"]),doc["value"]["message"]) for doc in self.config.find({"setting": {"$regex": "^reward_"}})]
    self.roles.sort(key=lambda t: t[0])
    self.immune_roles = self.config.find_one({"setting": "immune_roles"})["value"]["list"]
    self.VC_DAILY_CAP = int((self.config.find_one({"setting": "vc_daily_cap"}))["value"].get("hours", 2))
    self.VC_WINDOW = int((self.config.find_one({"setting": "vc_window"}))["value"].get("hours", 16))


  @commands.Cog.listener()
  async def on_message(self, message):
    if isinstance(message.channel, discord.DMChannel):
      return
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
    needed_exp = 100
    while total_exp >= needed_exp:
      level += 1
      needed_exp += 5 * level**2 + 50 * level
    current_level = level

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

  def exp_for_level(self, n: int = 0):
    if n <= 0:
      return 0
    return 5 * (n * (n - 1) * (2 * n - 1) // 6) + 25 * n * (n - 1) + 100 * n

# ------------------
# ------------------
# ---- COMMANDS ----
# ------------------
# ------------------

  @commands.command()
  @commands.guild_only()
  async def help(self, ctx: commands.Context, options: str = None):
    embed = Embed(title=f'Help', color=0xab94ab)
    if options == 'staff':
      embed.description = """Here's how you use my commands:
1. `!help` - Displays this message
2. `!set [user_id] [value] [type]` - Replace a user's current `text` or `voice` experience with `value`
3. `!award [user_id] [value] [type]` - Adds `value` to a user's `text` or `voice experience
4. `!config [view/edit/add] `\`\`\`[parameters]\`\`\` - View/adjust configs. Configs that rarely/never change are located in `.env` on the host machine
5. `!delete [user_id]` - Delete's a user's records from my database
"""
    else:
      embed.description = """Here's how you use my commands:
1. `!help` - Displays this message. For any staff reading this, please see `!help staff` if you need staff commands
2. `!level [user_id]` - See someone's current level/experience counts. Leave `[user_id]` blank to see your own
3. `!level up` - Restore your level roles, if you had any and lost them
4. `!wear [role name]` - Select a specific role/icon you want to display. Limited to 3 uses per hour
5. `!leaderboard [range]` - Displays the top `range` people on the leaderboard. Can also specify e.g. `25-75`
6. `!optout` - Opt out of the leveling system and deletes your EXP data. Contact staff to opt in again or restore levels
"""
    embed.set_footer(text='Greetings. I am the Count. They call me the Count because I LOVE to count')
    await ctx.send(embed=embed)

  @commands.command()
  async def optout(self, ctx: commands.Context):
    doc = self.users.find_one_and_delete({"_id": ctx.author.id})
    if not doc:
      await ctx.send('I could not find any data associated with you to opt you out.')
      return
    await ctx.send(f'You have been opted out and your experience data ({doc.get("text", 0)} text / {doc.get("voice", 0}) has been deleted from the database. To restore it and/or opt back in, contact staff.')
    optout = discord.utils.get(self.guild.roles, 'No Exp')
    await ctx.author.add_roles(optout)

  @commands.command()
  @commands.guild_only()
  @commands.cooldown(3, 60 * 60)
  async def wear(self, ctx: commands.Context, role_name: str):
    role = discord.utils.get(self.guild.roles, name="role_name")
    match = next((t for t in self.roles if t[1] == role.id), None)
    if not match:
      await ctx.send("After searching through every role in the server, I am left confused as to what role you mean when you say \"{role_name}\".")
      return

    doc = self.users.find_one({"_id": ctx.author.id})
    if not doc:
      self.users.insert_one({"_id": ctx.author.id})
      return

    accessbile = [t for t in self.roles if t[0] <= doc.get("level", 0)]
    if accessible:
      if role in accessible:
       if role in member.roles:
         await member.remove_roles(role)
       else:
         await member.add_roles(role)

  @commands.command()
  @commands.guild_only()
  @commands.cooldown(1, COMMAND_COOLDOWN)
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
    next_exp = self.exp_for_level(1 + doc.get("level", 0))
    progress = (current_exp - old_exp) / (next_exp - old_exp) * 100
    embed.add_field(name='Progress', value=f'{current_exp - old_exp} / {next_exp - old_exp} ({progress:.1f}%)', inline=True)
    embed.add_field(name='Next Role', value=next((f'<@&{r}>' for t, r, m in self.roles if t > current_level), 'None!'), inline=True)

    embed.set_footer(text="TIP: Commands do not grant experience points.")
    await ctx.send(embed=embed)



  @commands.command()
  @commands.guild_only()
  @commands.cooldown(1, COMMAND_COOLDOWN)
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
      duration = datetime.now(timezone.utc) - doc["joined"]
      granted = self.apply_daily_cap(member_id, doc["joined"], duration)
      if granted > timedelta(0):
        await self.internal_award(member_id, calculate(timedelta=granted), "voice")

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
        "last_vc_join_time": joined,
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
