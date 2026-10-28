import discord
from discord.ext import commands, tasks
from discord import Member, Status, User, Reaction, Message, Embed, ApplicationContext, Option

from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from pymongo import ReturnDocument

from datetime import datetime, timedelta, timezone

from buttons.OptOut import OptOut
from buttons.RevealButton import RevealButton

from bson.int64 import Int64
import io
import json
import os
import dotenv

GUILD = int(os.environ['OPERATING_GUILD'])
COMMAND_COOLDOWN = os.environ['COMMAND_COOLDOWN']

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

  @commands.slash_command(description='Delete all your experience data and opt out from receiving any more', guild_ids=[GUILD])
  async def optout(self, ctx: ApplicationContext):
    await ctx.respond('Opting out will delete all your experience data. Are you sure you want to do this?', view=OptOutView(self, ctx.author), ephemeral=True)

  def update_database(self):
    self.roles = [(int(doc["value"]["threshold"]),int(doc["value"]["role_id"]),doc["value"]["role_name"],doc["value"]["message"],doc["value"]["persistent"]=="True") for doc in self.config.find({"setting": {"$regex": "^reward_"}})]
    self.roles.sort(key=lambda t: t[0])
    self.immune_roles = self.config.find_one({"setting": "immune_roles"})["value"]["list"]

  @commands.slash_command(description="View the commands I can run", guild_ids=[GUILD])
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

  async def construct_role_list(ctx: discord.AutocompleteContext):
    id = ctx.interaction.user.id
    current_level = ctx.cog.users.find_one({"_id": id})
    typed = ctx.value.lower()
    return [t[2] for t in ctx.cog.roles if t[2].lower().startswith(typed) and not t[4] and current_level.get("level", 0) >= t[0]]

  @commands.slash_command(description="Wear a new level role for its icon/color", guild_ids=[GUILD])
  @commands.cooldown(1, COMMAND_COOLDOWN, commands.BucketType.member)
  async def wear(self, ctx: ApplicationContext,
                 role_name: Option(str, 'Name of the role you would like to equip.', name="role_name", autocomplete=construct_role_list, required=True)):
    await ctx.defer(ephemeral=True)
    role = discord.utils.find(
      lambda r: r.name.casefold() == role_name.casefold(),
      self.guild.roles,
    )
    match = next((t for t in self.roles if role and t[1] == role.id), None)
    if not match:
      await ctx.followup.send(f"After searching through every role in the server, I am left confused as to what role you mean when you say \"{role_name}\".",
                        ephemeral=True)
      return

    doc = self.users.find_one({"_id": ctx.author.id}) or {}
    if match[0] > doc.get("level", 0):
      await ctx.followup.send("I have counted every experience point you have, and determined you have not reached the level required for that role.", ephemeral=True)
      return

    thresholds = {t[1]: t[0] for t in self.roles if not t[4]}
    to_remove = [
      r for r in ctx.author.roles
      if r.id in thresholds and r.id != role.id
    ]
    if to_remove:
      await ctx.author.remove_roles(*to_remove)
    if role not in ctx.author.roles:
      await ctx.author.add_roles(role)

    await ctx.followup.send("You are hereby awarded the role you seek.", ephemeral=True)
    self.users.update_one(
      {"_id": ctx.author.id},
      {"$set": {"preference": role.id}},
      upsert=True,
    )

  @commands.slash_command(description='Restore your level roles/permissions.', guild_ids=[GUILD])
  @commands.cooldown(1, COMMAND_COOLDOWN, commands.BucketType.member)
  async def restore(self, ctx: ApplicationContext):
    doc = self.users.find_one({"_id": ctx.author.id})
    if doc:
      await self.check(doc)
      await ctx.respond("Successfully counted every last experience point and awarded you with the associated roles.", ephemeral=True)

  @commands.slash_command(description="Check your level or somebody else's", guild_ids=[GUILD])
  @commands.cooldown(1, COMMAND_COOLDOWN, commands.BucketType.member)
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

    old_exp = self.exp_for_level(doc.get("level", 0))
    next_exp = self.exp_for_level(doc.get("level", 0) + 1)
    progress = ((current_exp - old_exp) / (next_exp - old_exp)) * 100
    embed.add_field(name='Progress', value=f'{current_exp - old_exp} / {next_exp - old_exp} ({progress:.1f}%)', inline=True)
    embed.add_field(name='Next Role', value=next((f'<@&{r}> at level **{t}**' for t, r, n, m, p in self.roles if t > current_level), 'None!'), inline=True)

    next_role_exp = self.exp_for_level(next((t[0] for t in self.roles if t[0] > current_level), 0))
    if next_role_exp != 0:
      next_role_progress = ((current_exp) / next_role_exp) * 100
      embed.add_field(name='Progress Towards Next Role', value=f'{current_exp} / {next_role_exp} ({next_role_progress:.2f}%)', inline=True)

    embed.set_footer(text="TIP: Commands do not grant experience points.")
    await ctx.respond(embed=embed, ephemeral=True)



  @commands.slash_command(description="Check out the weekly, monthly, or overall leaderboards!", guild_ids=[GUILD])
  @commands.cooldown(1, COMMAND_COOLDOWN, commands.BucketType.member)
  async def leaderboard(self, ctx: ApplicationContext,
                        range: Option(str, 'Area of the leaderboard you wish to see, e.g. "10" or "50-80"', default="10", name="range"),
                        timespan: Option(str, 'Timespan you wish to view', default="All Time", name="timespan", choices=['All Time', 'Weekly', "Monthly"]),
                        sort_type: Option(str, 'Method you wish to use to sort the leaderboard', default='Voice & Text', name="sort_type", choices=['Voice & Text', "Around Me", "Voice", "Text"])):
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

    if sort_type == "Around Me":
      db, first_rank, pipeline = self.around_me_pipeline(timespan, ctx.author.id, limit)
      if db is not None and pipeline is None:
        await ctx.respond("No EXP recorded in this timespan.", ephemeral=True)
        return
    else:
      db, pipeline = self.build_pipeline(timespan, sort_type, skip, limit)
      first_rank = start

    if db is None:
      await ctx.respond("I do not understand this type of leaderboard you're talking about. I only keep count of `Weekly` and `Monthly` leaderboards in addition to `All Time`.", ephemeral=True)
      return

    lines = []
    for rank, doc in enumerate(db.aggregate(pipeline), start=first_rank):
      text = doc.get("text", 0)
      voice = doc.get("voice", 0)
      level = f' Level `{doc.get("level", 0)}`' if timespan == "All Time"  else ""
      lines.append(f'{rank}. <@{doc["_id"]}>{level} - **{text + voice}** Total (**{text}** Text / **{voice}** VC)')

    embed = Embed(title=f"{timespan} Leaderboard ({sort_type})", description="\n".join(lines) or "No results.", color=0xA9BFBE)
    reveal_button = RevealButton(embed=embed)
    await ctx.respond(embed=embed, view=reveal_button, ephemeral=True)

  def base_stages(self, timespan):
    if timespan == "All Time":
      return self.users, []
    elif timespan == "Weekly":
      days = 7
    elif timespan == "Monthly":
      days = 30
    else:
      return None, None
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = today - timedelta(days=days - 1)
    return self.recent, [
      {"$match": {"date": {"$gte": cutoff}}},
      {"$group": {
        "_id": "$user",
        "text": {"$sum": "$text"},
        "voice": {"$sum": "$voice"},
      }},
    ]

  def build_pipeline(self, timespan, sort_type, skip, limit):
    collection, base = self.base_stages(timespan)
    options = {
      "Voice & Text": {"$add": [
        {"$ifNull": ["$text", 0]},
        {"$ifNull": ["$voice", 0]},
      ]},
      "Voice": {"$ifNull": ["$voice", 0]},
      "Text": {"$ifNull": ["$text", 0]}
    }
    exp = options.get(sort_type)
    if collection is None or exp is None or sort_type == "Around Me":
      return None, None
    return collection, base + [
      {"$addFields": {"total_exp": exp}},
      {"$sort": {"total_exp": -1, "_id": 1}},
      {"$skip": skip},
      {"$limit": limit},
    ]

  def around_me_pipeline(self, timespan, user_id, limit):
    collection, base = self.base_stages(timespan)
    if collection is None:
      return None, None, None
    scored = base + [{"$addFields": {"total_exp": {"$add": [{"$ifNull": ["$text", 0]},{"$ifNull": ["$voice", 0]}]}}}]

    me = list(collection.aggregate(scored + [{"$match": {"_id": user_id}}]))
    if not me:
      return collection, None, None
    user_total = me[0]["total_exp"]

    before = list(collection.aggregate(scored + [
      {"$match": {"$expr": {"$or": [
        {"$gt": ["$total_exp", user_total]},
        {"$and": [
          {"$eq": ["$total_exp", user_total]},
          {"$lt": ["$_id", user_id]},
        ]},
      ]}}},
      {"$count": "n"},
    ]))
    index = before[0]["n"] if before else 0
    skip = max(0, index - limit // 2)
    return collection, index + 1, scored + [
      {"$sort": {"total_exp": -1, "_id": 1}},
      {"$skip": skip},
      {"$limit": limit},
    ]

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

    level_role_ids = {t[1] for t in self.roles if not t[4]}
    to_remove = [r for r in user.roles if r.id in level_role_ids and r.id != role.id]
    if to_remove:
      await user.remove_roles(*to_remove)

    if role not in user.roles:
      await user.add_roles(role)


  def exp_for_level(self, n: int = 0):
    if n <= 0:
      return 0
    return 5 * (n * (n - 1) * (2 * n - 1) // 6) + 25 * n * (n - 1) + 100 * n

  @commands.Cog.listener()
  async def on_application_command_error(self, ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
      await ctx.respond(f"You cannot expect me to respond that fast after you just ran this command. Try again in {error.retry_after:.1f}s.", ephemeral=True,)
    else:
      raise error
