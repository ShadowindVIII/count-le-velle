import discord
from discord.ext import commands, tasks
from discord import Member, Status, User, Reaction, Message, Embed, ApplicationContext, Option

from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from pymongo import ReturnDocument

from datetime import datetime, timedelta, timezone

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

class Housekeeping(commands.Cog):
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
    self.roles = [(int(doc["value"]["threshold"]),int(doc["value"]["role_id"]),doc["value"]["message"]) for doc in self.config.find({"setting": {"$regex": "^reward_"}})]
    self.roles.sort(key=lambda t: t[0])
    self.immune_roles = self.config.find_one({"setting": "immune_roles"})["value"]["list"]

  @commands.slash_command(description="View the commands I can run")
  @commands.guild_only()
  async def help(self, ctx: ApplicationContext, options: Option(str, 'View other categories of help. Leave blank if you\'re not staff.', default=None, name="options")):
    embed = Embed(title=f'Help', color=0xab94ab)
    if options == 'staff':
      embed.description = f"""Here's how you use my commands:
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

My privacy policy can be found at {os.environ['PRIVACY_POLICY_URL']}
"""
    embed.set_footer(text='Greetings. I am the Count. They call me the Count because I LOVE to count')
    await ctx.respond(embed=embed, ephemeral=True)


