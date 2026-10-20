import discord
from discord.ext import commands
from discord import Member, Status, User, Reaction, Message, ApplicationContext, Option

import os
import dotenv

from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from pymongo import ReturnDocument, UpdateOne
from datetime import datetime, timedelta, timezone

import requests
import asyncio
import time

import asyncio
from pymongo import UpdateOne

ADMIN_ROLE_ID = int(os.environ["ADMIN_ROLE_ID"])
STAFF_ROLE_ID = int(os.environ["STAFF_ROLE_ID"])

class Admin(commands.Cog):
  def __init__(self, bot, mongo: MongoClient):
    self.bot = bot
    self.database = mongo.database
    self.users = mongo.database.users

  @commands.Cog.listener()
  async def on_ready(self):
    self.guild = await self.bot.fetch_guild(int(os.environ["OPERATING_GUILD"]))

  @commands.slash_command(description="Check my latency")
  @commands.guild_only()
  async def ping(self, ctx: ApplicationContext):
    init_text = 'Counting...'
    msg = await ctx.respond(init_text, ephemeral=True)
    delta_ms = ((ctx.message.created_at - msg.created_at).microseconds)/1000
    delta_s = abs(ctx.message.created_at - msg.created_at).seconds
    ping_text = 'Done counting! I responded in `%d.%03ds`' % (delta_s, delta_ms) + ' and have been running for ' + self.__uptime()
    await msg.edit(content=ping_text)

  @commands.command()
  @commands.guild_only()
  @commands.has_any_role(ADMIN_ROLE_ID, STAFF_ROLE_ID)
  async def fixvoice(self, ctx: commands.Context):
    await ctx.send('started')
    try:
      t = time.perf_counter()
      result = await asyncio.to_thread(
        self.users.update_many,
        {"vc": {"$exists": True}},
        [
          {"$set": {"voice": {"$ifNull": ["$voice", "$vc"]}}},
          {"$unset": "vc"},
        ],
      )
      await ctx.send(
        f'fixed {result.modified_count} in {time.perf_counter() - t:.1f}s'
      )
    except Exception as e:
      await ctx.send(f'error: {type(e).__name__}: {e}')
      raise

  @commands.command()
  @commands.guild_only()
  @commands.has_any_role(ADMIN_ROLE_ID, STAFF_ROLE_ID)
  async def transfer(self, ctx: commands.Context, filename: str):
    with open(filename, encoding="utf-8") as f:
      data = json.load(f)

    await ctx.send('Initiating transfer...')
    ops = []
    for key, raw in data.items():
      item = json.loads(raw) if isinstance(raw, str) else raw
      text = int(round(float(item["text"])))
      voice = int(round(float(item["voice"])))
      ops.append(UpdateOne(
        {"_id": int(key)},
        {
          "$set": {
            "text": text,
            "voice": voice,
            "level": exp_to_level(text + voice),
          },
          "$setOnInsert": {"preference": 0},
        },
        upsert=True,
      ))

    result = await asyncio.to_thread(self.users.bulk_write, ops)
    await ctx.send(
      f'done! matched {result.matched_count}, inserted {result.upserted_count}'
    )

  @commands.command()
  @commands.guild_only()
  @commands.has_any_role(ADMIN_ROLE_ID, STAFF_ROLE_ID)
  async def delete(self, ctx: commands.Context, id: int = 0):
    doc = self.users.find_one_and_delete({"_id": ctx.author.id})
    if not doc or id == 0:
      await ctx.send('No data associated with <@{id}> / {id}.')
      return
    await ctx.send(f'Purged data for <@{id}> / {id} ({doc.get("text", 0)} text / {doc.get("voice", 0)}) from database.')

  @commands.command()
  @commands.guild_only()
  @commands.has_any_role(ADMIN_ROLE_ID, STAFF_ROLE_ID)
  async def set(self, ctx: commands.Context, recipient: int = 0, amount: int = 0, type: str = "text"):
    if recipient == 0:
      return
    doc = self.users.find_one({"_id": recipient})

    if type == "text":
      new_doc = self.users.find_one_and_update(
        {"_id": recipient},
        {"$set": {"text": amount}},
        upsert=True,
        return_document=ReturnDocument.AFTER
      )
    if type == "voice":
      new_doc = self.users.find_one_and_update(
        {"_id": recipient},
        {"$set": {"voice": amount}},
        upsert=True,
        return_document=ReturnDocument.AFTER
      )

    await self.check(new_doc)
    await ctx.send(content=f"Successfully updated <@{recipient}>'s **{type}** experience to **{amount}**.",allowed_mentions=discord.AllowedMentions.none())

  @commands.command()
  @commands.guild_only()
  @commands.has_any_role(ADMIN_ROLE_ID, STAFF_ROLE_ID)
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
    await ctx.send(content=f"Successfully added **{amount}** to <@{recipient}>'s **{type}** experience.",allowed_mentions=discord.AllowedMentions.none())

  @commands.command()
  @commands.guild_only()
  @commands.has_any_role(ADMIN_ROLE_ID, STAFF_ROLE_ID)
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
        await ctx.send(f'# Previewing {setting if setting not in [None, ""] else "every"} config:\n```css\n{content}```')
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
    needed_exp = 100
    while total_exp >= needed_exp:
      level += 1
      needed_exp += 5 * level**2 + 50 * level + 100
    current_level = level

    prev_level = doc.get("level")
    if prev_level != current_level:
      self.users.update_one({"_id": doc["_id"]}, {"$set": {"level": current_level}})
