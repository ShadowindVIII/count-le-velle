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

class Housekeeping(commands.Cog):
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
    self.roles = [(int(doc["value"]["threshold"]),int(doc["value"]["role_id"]),doc["value"]["message"]) for doc in self.config.find({"setting": {"$regex": "^reward_"}})]
    self.roles.sort(key=lambda t: t[0])
    self.immune_roles = self.config.find_one({"setting": "immune_roles"})["value"]["list"]

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

My privacy policy can be found at https://leapzard.app/reginald.html
"""
    embed.set_footer(text='Greetings. I am the Count. They call me the Count because I LOVE to count')
    await ctx.send(embed=embed)

  @commands.command()
  async def optout(self, ctx: commands.Context):
    doc = self.users.find_one_and_delete({"_id": ctx.author.id})
    if not doc:
      await ctx.send('I could not find any data associated with you to opt you out.')
      return
    await ctx.send(f'You have been opted out and your experience data ({doc.get("text", 0)} text / {doc.get("voice", 0)}) has been deleted from the database. To restore it and/or opt back in, contact staff.')
    optout = discord.utils.get(self.guild.roles, 'No Exp')
    await ctx.author.add_roles(optout)
