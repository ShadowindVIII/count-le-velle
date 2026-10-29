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

COMMAND_COOLDOWN = os.environ['COMMAND_COOLDOWN']

class Text(commands.Cog):
  def __init__(self, bot, mongo: MongoClient):
    self.bot = bot
    self.users = mongo.database.users
    self.recent = mongo.database.recent
    self.config = mongo.database.config
    self.recent.create_index([("user", 1), ("date", 1)], unique=True)
    self.recent.create_index("date", expireAfterSeconds=30 * 86400)
    self.update_database()

  @commands.Cog.listener()
  async def on_ready(self):
    self.guild = await self.bot.fetch_guild(int(os.environ["OPERATING_GUILD"])) 
    self.update_database()

  def update_database(self):
    self.TIME_INCREMENT = int((self.config.find_one({"setting": "time_increment"}))["value"].get("value", 10))
    self.TEXT_AWARD = int((self.config.find_one({"setting": "text_award"}))["value"].get("value", 3))
    debug = (self.config.find_one({"setting": "debug"}))["value"]
    self.DEBUG = [debug.get("enabled", "True") == "True", int(debug.get("category_id", 0))]


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
    if any(a.id in exp.immune_roles for a in message.author.roles):
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
      await exp.check(new_doc)

  def calculate(self, message: discord.Message = None):
    return self.TEXT_AWARD