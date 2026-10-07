import discord
from discord.ext import commands
from discord import Member, Status, User, Reaction, Message

import os
import dotenv

from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi

class Admin(commands.Cog):
  def __init__(self, bot, mongo: MongoClient):
    self.bot = bot
    self.database = mongo.database
    self.sudo_id = int(os.environ["ADMIN_ROLE_ID"])

# filler for now...
