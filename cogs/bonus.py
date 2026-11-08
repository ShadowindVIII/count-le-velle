import discord
from discord.ext import commands, tasks
from discord import Member, Status, User, Reaction, Message, Embed, ApplicationContext, Option

from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from pymongo import ReturnDocument

from datetime import datetime, timedelta, timezone

import os
import dotenv
import exphelper as exp

class Bonus(commands.Cog):
  def __init__(self, bot, mongo: MongoClient):
    self.bot = bot
    self.users = mongo.database.users
    self.recent = mongo.database.recent
    self.config = mongo.database.config
    self.update_database()

  @commands.Cog.listener()
  async def on_ready(self):
    self.guild = await self.bot.fetch_guild(int(os.environ["OPERATING_GUILD"])) 
    self.update_database()

  def update_database(self):
    self.TIME_INCREMENT = int((self.config.find_one({"setting": "time_increment"}))["value"].get("value", 10))
    self.BONUS_AWARD = int(self.config.find_one({"setting": "bonus_award"})["value"].get("value", 375))
    debug = (self.config.find_one({"setting": "debug"}))["value"]
    self.DEBUG = [debug.get("enabled", "True") == "True", int(debug.get("category_id", 0))]
    self.BONUS_CHANNELS = self.config.find_one({"setting": "bonus_channels"})["value"].get("channels", {})
    self.BONUS_DAILY_CAP = int(self.config.find_one({"setting": "bonus_daily_cap"})["value"].get("value", 3))

  @commands.Cog.listener()
  async def on_message(self, message):
    if message.guild is None:
      return
    if self.DEBUG[0] and not (message.channel.category_id == self.DEBUG[1]):
      return
    if message.author.bot:
      return
    if message.content.startswith(self.bot.command_prefix):
      return
    if any(a.id in exp.immune_roles for a in message.author.roles):
      return
    if isinstance(message.type, discord.MessageType.pins_add):
      return
    # For the Rain World server, BONUS_CHANNELS contains all gallery channels + stories-library
    if message.channel.id not in self.BONUS_CHANNELS.get(str(message.channel.category_id), []):
      return

    now = datetime.now(timezone.utc)
    date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    doc = self.users.find_one({"_id": message.author.id})
    if not doc:
      self.users.insert_one({"_id": message.author.id, "last_msg_date": now})
      self.recent.insert_one({"user": message.author.id, "date": date, "bonuses": {str(message.channel.category.id): 1}})
      return

    if doc.get("last_msg_date"):
      if now - doc.get("last_msg_date") < timedelta(seconds=self.TIME_INCREMENT):
        return
    self.users.update_one(
      {"_id": message.author.id},
      {"$set": {"last_msg_date": now}},
      upsert=True
    )

    bonuses = (self.recent.find_one({"user": message.author.id, "date": date}) or {}).get("bonuses", {})
    if int(bonuses.get(str(message.channel.category.id),0)) >= self.BONUS_DAILY_CAP:
      return
    self.recent.update_one(
      {"user": message.author.id, "date": date},
      {"$inc": {f"bonuses.{message.channel.category.id}": 1}},
      upsert=True
    )

    await exp.internal_award(recipient=message.author.id, amount=self.calculate(message), type="bonus")

  def calculate(self, message: discord.Message = None):
    return self.BONUS_AWARD
