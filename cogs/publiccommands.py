import discord
from discord.ext import commands, tasks
from discord import Member, Status, User, Reaction, Message, Embed, ApplicationContext, Option

from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from pymongo import ReturnDocument

from datetime import datetime, timedelta, timezone

from bson.int64 import Int64
import io
import json
import os
import dotenv

COMMAND_COOLDOWN = os.environ['COMMAND_COOLDOWN']

class OptOutView(discord.ui.View):
  def __init__(self, cog, user):
    super().__init__(timeout=60)
    self.cog = cog
    self.user = user

  @discord.ui.button(label='Confirm', style=discord.ButtonStyle.danger)
  async def confirm(self, button, interaction):
    await interaction.response.defer()
    doc = self.cog.users.find_one({"_id": self.user.id})
    recent_count = self.cog.recent.count_documents({"user": self.user.id})
    if not doc and not recent_count:
      await interaction.edit_original_response(content='It seems you have no data associated with your account with which to opt out.', view=None)
      return
    channel_id = int(os.environ['LOG_CHANNEL'])
    log_channel = self.cog.bot.get_channel(channel_id)
    if log_channel is None:
      log_channel = await self.cog.bot.fetch_channel(channel_id)
    payload = json.dumps(doc, default=str, indent=2)
    await log_channel.send(
      f'Opt-out: {self.user} ({self.user.id}), {recent_count} recent entries deleted.',
      file=discord.File(io.BytesIO(payload.encode()), filename=f'optout_{self.user.id}.json')
    )
    self.cog.users.delete_one({"_id": self.user.id})
    self.cog.recent.delete_many({"user": self.user.id})
    role = discord.utils.get(interaction.guild.roles, name='No Exp')
    if role:
      await self.user.add_roles(role)
    if doc:
      text = doc.get("text", 0)
      voice = doc.get("voice", 0)
    else:
      text = 0
      voice = 0

    await interaction.edit_original_response(content=f'You have been opted out and your experience data ({text} text / {voice} voice) has been deleted. To restore it and/or opt back in, contact staff.', view=None)

  @discord.ui.button(label='Cancel', style=discord.ButtonStyle.secondary)
  async def cancel(self, button, interaction):
    await interaction.response.edit_message(content='Cancelled.', view=None)

class PublicCommands(commands.Cog):
  def __init__(self, bot, mongo: MongoClient):
    self.bot = bot
    self.recent = mongo.database.recent
    self.users = mongo.database.users
    self.config = mongo.database.config
    self.update_database()

  @commands.Cog.listener()
  async def on_ready(self):
    self.guild = await self.bot.fetch_guild(int(os.environ["OPERATING_GUILD"])) 
    self.update_database()

  @commands.slash_command(description='Delete all your experience data and opt out from receiving any more')
  async def optout(self, ctx: ApplicationContext):
    await ctx.respond('Opting out will delete all your experience data. Are you sure you want to do this?', view=OptOutView(self, ctx.author), ephemeral=True)

  def update_database(self):
    self.roles = [(int(doc["value"]["threshold"]),int(doc["value"]["role_id"]),doc["value"]["message"],doc["value"]["persistent"]=="True") for doc in self.config.find({"setting": {"$regex": "^reward_"}})]
    self.roles.sort(key=lambda t: t[0])
    self.immune_roles = self.config.find_one({"setting": "immune_roles"})["value"]["list"]

  @commands.slash_command(description="View the commands I can run")
  @commands.guild_only()
  async def help(self, ctx: ApplicationContext, options: Option(str, 'View other categories of help. Leave blank if you\'re not staff.', default=None, name="options")):
    embed = Embed(title=f'Help', color=0xab94ab)
    if options == 'staff':
      embed.description = f"""Here's how you use my commands:
1. `{os.environ['PREFIX']}help` - Displays this message
2. `{os.environ['PREFIX']}set [user_id] [value] [type]` - Replace a user's current `text` or `voice` experience with `value`
3. `{os.environ['PREFIX']}award [user_id] [value] [type]` - Adds `value` to a user's `text` or `voice experience
4. `{os.environ['PREFIX']}config [view/edit/add] `\`\`\`[parameters]\`\`\` - View/adjust configs. Configs that rarely/never change are located in `.env` on the host machine
5. `{os.environ['PREFIX']}delete [user_id]` - Delete's a user's records from my database
"""
    else:
      if os.environ['PRIVACY_POLICY_URL'] != "https://example.com":
        privacy = f"\n\nMy Privacy Policy can be found [here]({os.environ['PRIVACY_POLICY_URL']})"
      else:
        privacy = ""
      embed.description = f"""Here's how you use my commands:
1. `/help` - Displays this message. For any staff reading this, please see `!help staff` if you need staff commands
2. `/level [user_id]` - See someone's current level/experience counts. Leave `[user_id]` blank to see your own
3. `/restore` - Restore your level roles, if you had any and lost them
4. `/wear [role name]` - Select a specific role/icon you want to display. Limited to 3 uses per hour
5. `/leaderboard [range]` - Displays the top `range` people on the leaderboard. Can also specify e.g. `25-75`
6. `/optout` - Opt out of the leveling system and deletes your EXP data. Contact staff to opt in again or restore levels{privacy}
"""
    embed.set_footer(text='Greetings. I am the Count. They call me the Count because I LOVE to count')
    await ctx.respond(embed=embed, ephemeral=True)



  @commands.slash_command(description="Wear a new level role for its icon/color")
  @commands.guild_only()
  @commands.cooldown(1, COMMAND_COOLDOWN, commands.BucketType.member)
  async def wear(self, ctx: ApplicationContext,
                 role_name: Option(str, 'Name of the role you would like to equip.', default=None, name="role_name")):
    role = discord.utils.find(
      lambda r: r.name.casefold() == role_name.casefold(),
      self.guild.roles,
    )
    match = next((t for t in self.roles if role and t[1] == role.id), None)
    if not match:
      await ctx.respond(f"After searching through every role in the server, I am left confused as to what role you mean when you say \"{role_name}\".",
                        ephemeral=True)
      return

    doc = self.users.find_one({"_id": ctx.author.id}) or {}
    if match[0] > doc.get("level", 0):
      await ctx.respond("I have counted every experience point you have, and determined you have not reached the level required for that role.", ephemeral=True)
      return

    thresholds = {t[1]: t[0] for t in self.roles if not t[3]}
    to_remove = [
      r for r in ctx.author.roles
      if r.id in thresholds and r.id != role.id
    ]
    if to_remove:
      await ctx.author.remove_roles(*to_remove)
    if role not in ctx.author.roles:
      await ctx.author.add_roles(role)

    await ctx.respond("You are hereby awarded the role you seek.", ephemeral=True)
    self.users.update_one(
      {"_id": ctx.author.id},
      {"$set": {"preference": role.id}},
      upsert=True,
    )

  @commands.slash_command(description='Restore your level roles/permissions.')
  @commands.guild_only()
  @commands.cooldown(1, COMMAND_COOLDOWN)
  async def restore(self, ctx: ApplicationContext):
    doc = self.users.find_one({"_id": ctx.author.id})
    if doc:
      await self.check(doc)
      await ctx.respond("Successfully counted every last experience point and awarded you with the associated roles.", ephemeral=True)

  @commands.slash_command(aliases=['levelle'], description="Check your level or somebody else's")
  @commands.guild_only()
  @commands.cooldown(1, COMMAND_COOLDOWN)
  async def level(self, ctx: ApplicationContext,
                  option: Option(str, 'ID of the user you wish to check. Leave blank to view your level.', default="0", name="user")):
    await ctx.response.defer(ephemeral=True)
    try:
      id = int(option)
    except ValueError:
      return await ctx.followup.send("Invalid user ID.", ephemeral=True)
    if id == 0:
      id = ctx.author.id

    try:
      user = await self.guild.fetch_member(id)
    except (discord.NotFound, discord.HTTPException):
      user = None

    if not user:
      await ctx.followup.send(f"I have thoroughly checked every tome and scroll in my library and found none for this `{option}` person!", ephemeral=True)
      return
    doc = self.users.find_one({"_id": id})
    if not doc:
      await ctx.followup.send(f"It seems as though this `{option}` person has no experience data for me to count!", ephemeral=True)
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
    progress = ((current_exp - old_exp) / (next_exp - old_exp)) * 100
    embed.add_field(name='Progress', value=f'{current_exp - old_exp} / {next_exp - old_exp} ({progress:.1f}%)', inline=True)
    embed.add_field(name='Next Role', value=next((f'<@&{r}>' for t, r, m in self.roles if t > current_level), 'None!'), inline=True)

    embed.set_footer(text="TIP: Commands do not grant experience points.")
    await ctx.respond(embed=embed, ephemeral=True)



  @commands.slash_command(description="Check out the weekly, monthly, or overall leaderboards!")
  @commands.guild_only()
  @commands.cooldown(1, COMMAND_COOLDOWN)
  async def leaderboard(self, ctx: ApplicationContext,
                        range: Option(str, 'Area of the leaderboard you wish to see, e.g. "10" or "50-80"', default="10", name="range"),
                        type: Option(str, 'Category of leaderboard you wish to view', default="All Time", name="type", choices=['Overall', 'Weekly', "Monthly"])):
    await ctx.response.defer(ephemeral=True)
    low, sep, high = range.partition("-")
    try:
      if sep:
        start, finish = int(low), int(high)
      else:
        start, finish = 1, int(low)
    except ValueError:
      await ctx.respond("Usage: `!leaderboard n` for the top `n` people or `!leaderboard 50-80` (capped at 30)", ephemeral=True)
      return

    if start < 1 or finish <= start or finish - start > 30:
      await ctx.respond(f"You cannot possibly expect me to count through such a range. "
                        f"You shall specify it to me in the correct formatting (e.g. `10-25`) and may only request at most THIRTY results at a time. No more!",
                        ephemeral=True)
      return

    skip = start - 1
    limit = finish - start + 1

    if type == "All Time":
      db = self.users
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
    elif type == "Weekly":
      db = self.recent
      pipeline = self.recent_pipeline(7, skip, limit)
    elif type == "Monthly":
      db = self.recent
      pipeline = self.recent_pipeline(30, skip, limit)
    else:
      await ctx.respond(f"I do not understand this \"{type}\" type of leaderboard you're talking about. "
                        f"I only keep count of `Weekly` and `Monthly` leaderboards in addition to `All Time`.", ephemeral=True)
      return

    description = "\n".join(
      f'{rank}. <@{doc["_id"]}> Level `{doc.get("level", 0)}` '
      f'- **{doc.get("text", 0) + doc.get("voice", 0)}** Total '
      f'(**{doc.get("text", 0)}** Text / **{doc.get("voice", 0)}** VC)'
      for rank, doc in enumerate(db.aggregate(pipeline), start=start)
    )
    embed = Embed(title=f"{type} Leaderboard", description=description, color=0xA9BFBE)
    await ctx.respond(embed=embed, ephemeral=True)

  def recent_pipeline(self, days, skip, limit):
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = today - timedelta(days=days - 1)
    return [
      {"$match": {"date": {"$gte": cutoff}}},
      {"$group": {
        "_id": "$user",
        "text": {"$sum": "$text"},
        "voice": {"$sum": "$voice"},
      }},
      {"$addFields": {"total_exp": {"$add": ["$text", "$voice"]}}},
      {"$sort": {"total_exp": -1, "_id": 1}},
      {"$skip": skip},
      {"$limit": limit},
    ]

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

  def calculate(self, message: discord.Message = None):
    return self.TEXT_AWARD

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

    eligible = [t for t in self.roles if current_level >= t[0]]
    if not eligible:
      return

    pref_id = doc.get("preference")
    pref = next((t for t in eligible if t[1] == pref_id), None)
    target = pref or max(eligible, key=lambda t: t[0])

    role = self.guild.get_role(target[1])
    if not role:
      role = await self.guild.fetch_role(target[1])

    level_role_ids = {t[1] for t in self.roles if not t[3]}
    to_remove = [r for r in user.roles if r.id in level_role_ids and r.id != role.id]
    if to_remove:
      await user.remove_roles(*to_remove)

    if role not in user.roles:
      await user.add_roles(role)
      if not pref:
        try:
          await user.send(target[2].strip("\"").replace("\\n","\n"))
        except discord.Forbidden:
          pass


  def exp_for_level(self, n: int = 0):
    if n <= 0:
      return 0
    return 5 * (n * (n - 1) * (2 * n - 1) // 6) + 25 * n * (n - 1) + 100 * n
