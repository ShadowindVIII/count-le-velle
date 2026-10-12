import discord
from discord.ext import commands
from discord import Member, Status, User, Reaction, Message

import os
import dotenv

from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from pymongo import ReturnDocument

ADMIN_ROLE_ID = int(os.environ["ADMIN_ROLE_ID"])

class Admin(commands.Cog):
  def __init__(self, bot, mongo: MongoClient):
    self.bot = bot
    self.database = mongo.database
    self.users = mongo.database.users

  @commands.Cog.listener()
  async def on_ready(self):
    self.guild = await self.bot.fetch_guild(int(os.environ["OPERATING_GUILD"]))

  @commands.command()
  @commands.guild_only()
  @commands.has_role(ADMIN_ROLE_ID)
  async def config(self, ctx: commands.Context, action: str = None, setting: str = None, *, params: str = None):
    collection = self.database.config
    attachment = ctx.message.attachments[0] if ctx.message.attachments else None

    if action not in ["edit", "add", "remove", "view", "refresh"]:
      await ctx.send("Invalid action. Use `edit`, `add`, `remove`, `view`, or `refresh`.")
      return

    if action == "view":
      import io
      if setting is None or setting == '':
        results = [doc['setting'] for doc in collection.find()]
        content = '\n'.join(results)
      else:
        result = collection.find_one({"setting": setting})
        if not result:
          await ctx.send(f"Setting `{setting}` not found.")
          return
        content = '\n'.join([f"{k}={v}" for k, v in result['value'].items()]).replace('\\\\', '\\')
        content.replace('\'','')

      if len(content) > 1900:
        buffer = io.BytesIO(content.encode('utf-8'))
        file = discord.File(fp=buffer, filename=f'{setting}.txt')
        await ctx.send(content='This config is too large to be output in a discord message, here is a text file instead:', file=file)
      else: 
        await ctx.send(f'# Previewing {setting} config:\n```css\n{content}```')
      return

    if action == "remove":
      result = collection.delete_one({"setting": setting})
      if result.deleted_count > 0:
        self.refresh_databases()
        await ctx.send(f"Successfully removed setting `{setting}`.")
      else:
        await ctx.send(f"Setting `{setting}` not found.")
      return
    
    if action == "refresh":
      self.refresh_databases()
      await ctx.send("Refreshed the database cache.")
      return
      
    if action in ["edit", "add"]:
      if not params and not attachment:
        await ctx.send("Please provide parameters using triple backticks or upload a `.txt` file with `key=value` and `key=[value1, value2]` lines.")
        return

      try:
        if attachment and attachment.filename.endswith('.txt'):
          content = await attachment.read()
          parameters = self.parse_parameters(content.decode('utf-8'))
          setting = setting if setting else attachment.filename.replace('.txt','')
        else:
          parameters = self.parse_parameters(params[3:-3])  # Strip triple backticks
      except Exception as e:
        await ctx.send(f"Error parsing parameters: {e}")
        return

      formatted_result = '```\n' + '\n'.join([f"{k}={v}" for k, v in parameters.items()]) + '\n```'
      new_parameters = f'. Too long to display here, please use `.config view {setting}` if you wish to view results.' if len(formatted_result) > 1900 else f' with parameters:\n{formatted_result}'

      if action == "add":
        if collection.find_one({"setting": setting}):
          await ctx.send(f"Setting `{setting}` already exists. Use `.config edit` to modify it.")
          return
        collection.insert_one({"setting": setting, "value": parameters})
        self.refresh_databases()
        await ctx.send(f"Successfully added setting `{setting}`{new_parameters}")

      elif action == "edit":
        result = collection.update_one(
          {"setting": setting},
          {"$set": {"value": parameters}}
        )
        if result.matched_count > 0:
          self.refresh_databases()
          await ctx.send(f"Successfully updated setting `{setting}`{new_parameters}")
        else:
          await ctx.send(f"Setting `{setting}` not found. Use `.config add` to create it.")

  def parse_parameters(self, param_string: str):
    parameters = {}
    for param in param_string.split("\n"):
      if not param.strip():
        continue
      key, value = param.split("=", 1)
      key = key.strip()
      value = self.parse_value(value)
      parameters[key] = value

    return parameters

  def parse_value(self, value_string: str):
    value_string = value_string.strip()
    if value_string.startswith("[") and value_string.endswith("]"):
      items = self.split_dict(value_string[1:-1])
      return_value = [self.parse_value(item) for item in items]
    elif value_string.startswith("{") and value_string.endswith("}"):
      items = self.split_dict(value_string[1:-1])
      return_value = {self.parse_value(item[:item.index(":")]) : self.parse_value(item[item.index(":")+1:]) for item in items}
    else:
      try:
        return_value = int(value_string)
      except ValueError:
        try:
          return_value = float(value_string)
        except ValueError:
          return_value = value_string.strip("'")
    return return_value

  def split_dict(self, dict_string: str):
    bracket_count = 0
    splices = [0]
    for i in range(len(dict_string)):
      if dict_string[i] == '{' or dict_string[i] == '[':
        bracket_count += 1
      elif dict_string[i] == '}' or dict_string[i] == ']':
        bracket_count -= 1
      elif dict_string[i] == ',' and bracket_count == 0:
        splices.append(i)
    splices.append(len(dict_string))
    return [dict_string[splices[i]:splices[i+1]].strip(",").strip() for i in range(len(splices)-1)]

  def refresh_databases(self):
    for cog in self.bot.cogs.values():
      try:
        cog.update_database()
      except AttributeError:
        pass

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
  
  @commands.command()
  @commands.has_role(ADMIN_ROLE_ID)
  async def award(self, ctx: commands.Context, recipient: int = 0, amount: int = 0, type: str = "text"):
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
    await ctx.send(content=f"Successfully updated <@{recipient}>'s **{type}** experience to **{amount}**.",allowed_mentions=discord.AllowedMentions.none())
