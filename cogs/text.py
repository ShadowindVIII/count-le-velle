import discord
from discord.ext import commands, tasks
from discord import Member, Status, User, Reaction, Message, Embed

from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from pymongo import ReturnDocument

from datetime import datetime, timedelta, timezone

import os
import dotenv
COMMAND_COOLDOWN = os.environ['COMMAND_COOLDOWN']

class Text(commands.Cog):
  def __init__(self, bot, mongo: MongoClient):
    self.bot = bot
    self.users = mongo.database.users
    self.config = mongo.database.config
    self.update_database()

  @commands.Cog.listener()
  async def on_ready(self):
    self.guild = await self.bot.fetch_guild(int(os.environ["OPERATING_GUILD"])) 
    self.update_database()

  def update_database(self):
    self.TIME_INCREMENT = int((self.config.find_one({"setting": "time_increment"}))["value"].get("value", 10))
    self.TEXT_AWARD = int((self.config.find_one({"setting": "text_award"}))["value"].get("value", 3))
    self.roles = [(int(doc["value"]["threshold"]),int(doc["value"]["role_id"]),doc["value"]["message"]) for doc in self.config.find({"setting": {"$regex": "^reward_"}})]
    self.roles.sort(key=lambda t: t[0])
    self.immune_roles = self.config.find_one({"setting": "immune_roles"})["value"]["list"]
    debug = (self.config.find_one({"setting": "debug"}))["value"]
    self.DEBUG = [debug.get("enabled", "True") == "True", int(debug.get("category_id"))]


  @commands.Cog.listener()
  async def on_message(self, message):
    if message.guild is None:
      return
    if self.DEBUG[0] and not (message.channel.category_id == self.DEBUG[1]):
      return
    if message.author.bot:
      return
    if isinstance(message.channel, discord.VoiceChannel):
     return
    if message.content.startswith(self.bot.command_prefix):
      return
    if len(message.content) < 2 and not message.attachments:
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

    await self.internal_award(recipient=message.author.id, amount=self.calculate(message), type="text")

# ------------------
# ------------------
# ---- COMMANDS ----
# ------------------
# ------------------

  @commands.command()
  @commands.guild_only()
  @commands.cooldown(3, 60 * 60, commands.BucketType.user)
  async def wear(self, ctx: commands.Context, *, role_name: str):
    role = discord.utils.find(
      lambda r: r.name.casefold() == role_name.casefold(),
      self.guild.roles,
    )
    match = next((t for t in self.roles if role and t[1] == role.id), None)
    if not match:
      await ctx.send(f"After searching through every role in the server, I am left confused as to what role you mean when you say \"{role_name}\".")
      return

    doc = self.users.find_one({"_id": ctx.author.id}) or {}
    if match[0] > doc.get("level", 0):
      await ctx.send("I have counted every experience point you have, and determined you have not reached the level required for that role.")
      return

    thresholds = {t[1]: t[0] for t in self.roles}
    to_remove = [
      r for r in ctx.author.roles
      if r.id in thresholds and thresholds[r.id] < match[0]
    ]
    if to_remove:
      await ctx.author.remove_roles(*to_remove)
    if role not in ctx.author.roles:
      await ctx.author.add_roles(role)

    await ctx.send("You are hereby awarded the role you seek.")
    self.users.update_one(
      {"_id": ctx.author.id},
      {"$set": {"preference": role.id}},
      upsert=True,
    )

  @commands.command(aliases=['levelle'])
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

    old_exp = self.exp_for_level(doc.get("level", 0) - 1)
    next_exp = self.exp_for_level(doc.get("level", 0) + 1)
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
      await ctx.send("Usage: `!leaderboard n` for the top `n` people or `!leaderboard 50-80` (capped at 30)")
      return

    if start < 1 or finish <= start or finish - start > 30:
      await ctx.send(f"You cannot possibly expect me to count through such a range. You shall specify it to me in the correct formatting (e.g. `10-25`) and may only request at most THIRTY results at a time. No more!")
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
      f'{rank}. <@{doc["_id"]}> Level `{doc.get("level", 0)}` '
      f'- **{doc.get("text", 0) + doc.get("voice", 0)}** Total '
      f'(**{doc.get("text", 0)}** Text / **{doc.get("voice", 0)}** VC)'
      for rank, doc in enumerate(self.users.aggregate(pipeline), start=start)
    )
    embed = Embed(title="Leaderboard", description=description, color=0xA9BFBE)
    await ctx.send(embed=embed)


# -----------------
# -----------------
# --- INTERNALS ---
# -----------------
# -----------------

  async def internal_award(self, recipient: int = 0, amount: int = 0, type: str = "text"):
    if recipient == 0 or type not in ["text", "voice"]:
      return

    new_doc = self.users.find_one_and_update(
      {"_id": recipient},
      {"$inc": {type: amount}},
      upsert=True,
      return_document=ReturnDocument.AFTER
    )
    if new_doc:
      await self.check(new_doc)

  def calculate(self, message: discord.Message = None):
    return self.TEXT_AWARD

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
          await user.send(f"Congratulations **{user.nick or user.display_name}**, you just advanced to **level {current_level}**!")
        except discord.Forbidden:
          pass

    user_role_list = [role.id for role in user.roles]
    for threshold, role_id, message in self.roles:
      if current_level >= threshold and role_id not in user_role_list:
        role = self.guild.get_role(role_id)
        if not role:
          role = await self.guild.fetch_role(role_id)
        if int(doc.get("preference", None)):
          continue
        await user.add_roles(role)
        await user.send(message.strip("\""))


  def exp_for_level(self, n: int = 0):
    if n <= 0:
      return 0
    return 5 * (n * (n - 1) * (2 * n - 1) // 6) + 25 * n * (n - 1) + 100 * n

