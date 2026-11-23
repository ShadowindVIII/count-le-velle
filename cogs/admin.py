import json

import discord
from discord.ext import commands
from discord import Member, Status, User, Reaction, Message, ApplicationContext, Option, File, TextChannel, VoiceChannel, StageChannel, Thread

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

import exphelper as exp

ADMIN_ROLE_ID = int(os.environ["ADMIN_ROLE_ID"])
STAFF_ROLE_ID = int(os.environ["STAFF_ROLE_ID"])
GUILD = int(os.environ['OPERATING_GUILD'])

class Admin(commands.Cog):
  def __init__(self, bot, mongo: MongoClient):
    self.bot = bot
    self.database = mongo.database
    self.users = mongo.database.users
    self.recent = mongo.database.recent
    self.vc = mongo.database.vc
    self.start_time = discord.utils.utcnow()

  @commands.Cog.listener()
  async def on_ready(self):
    self.guild = await self.bot.fetch_guild(int(os.environ["OPERATING_GUILD"]))

  @commands.slash_command(guild_ids=[GUILD])
  @commands.has_any_role(ADMIN_ROLE_ID, STAFF_ROLE_ID)
  async def speak(self, ctx: ApplicationContext, channel: Option(TextChannel|VoiceChannel|StageChannel|Thread, "Channel to say stuff in", required=False), 
                  text: Option(str, "Let the record show I do NOT take lightly to shenanigans on your behalf!", required=True, default=None)
                  ):
    await channel.send(text)
    await ctx.respond(content='✅', ephemeral=True)

  @commands.slash_command(guild_ids=[GUILD])
  @commands.has_any_role(ADMIN_ROLE_ID, STAFF_ROLE_ID)
  async def ping(self, ctx: ApplicationContext):
    init_text = 'Counting...'
    msg = await ctx.response.send(init_text)
    delta_ms = ((ctx.message.created_at - msg.created_at).microseconds)/1000
    delta_s = abs(ctx.message.created_at - msg.created_at).seconds
    ping_text = 'Done counting! I responded in `%d.%03ds`' % (delta_s, delta_ms) + ' and have been running for ' + self.uptime()
    await msg.edit(content=ping_text)

#  @commands.slash_command(guild_ids=[GUILD])
#  @commands.has_any_role(ADMIN_ROLE_ID, STAFF_ROLE_ID)
#  async def transfer(self, ctx: ApplicationContext, filename: str):
#    with open(filename, encoding="utf-8") as f:
#      data = json.load(f)

#    await ctx.response.defer()
#    ops = []
#    for key, raw in data.items():
#      item = json.loads(raw) if isinstance(raw, str) else raw
#      text = int(round(float(item["text"])))
#      voice = int(round(float(item["voice"])))
#      ops.append(UpdateOne(
#        {"_id": int(key)},
#        {
#          "$set": {
#            "text": text,
#            "voice": voice,
#            "level": exp.exp_to_level(text + voice),
#          },
#          "$setOnInsert": {"preference": 0},
#        },
#        upsert=True,
#      ))

#    result = await asyncio.to_thread(self.users.bulk_write, ops)
#    await ctx.followup.send(f'Done! matched {result.matched_count}, inserted {result.upserted_count}')

  @commands.command(guild_ids=[GUILD])
  @commands.has_any_role(ADMIN_ROLE_ID, STAFF_ROLE_ID)
  async def delete(self, ctx: ApplicationContext, 
                   id: Option(int, "ID of the user whose experience you'd like to edit", name="member_id", required=True, default=0)
                   ):
    await ctx.response.defer()
    self.vc.delete_many({"_id": id})
    self.recent.delete_many({"user": id})
    doc = self.users.find_one_and_delete({"_id": ctx.author.id})
    if not doc or id == 0:
      await ctx.followup.respond('No data associated with <@{id}> / {id}.')
      return
    await ctx.followup.respond(f'Purged data for <@{id}> / {id} ({doc.get("text", 0)} text / {doc.get("voice", 0)} voice / {doc.get("bonus", 0)} bonus) from database.', allowed_mentions=discord.AllowedMentions.none())

  @commands.command(guild_ids=[GUILD])
  @commands.has_any_role(ADMIN_ROLE_ID, STAFF_ROLE_ID)
  async def set_exp(self, ctx: ApplicationContext, 
                    recipient: Option(int, "ID of the user whose experience you'd like to edit", name="member_id", required=True, default=0), 
                    amount: Option(int, "New value to set someone's experience to", name="amount", required=True, default=0), 
                    type: Option(str, "Type of exp you'd like to award", name="type", required=True, choies=["Text", "Voice", "Bonus"], default="Text")):
    if recipient == 0:
      return
    doc = self.users.find_one({"_id": recipient})

    if type == "Text":
      new_doc = self.users.find_one_and_update(
        {"_id": recipient},
        {"$set": {"text": amount}},
        upsert=True,
        return_document=ReturnDocument.AFTER
      )
    if type == "Voice":
      new_doc = self.users.find_one_and_update(
        {"_id": recipient},
        {"$set": {"voice": amount}},
        upsert=True,
        return_document=ReturnDocument.AFTER
      )
    if type == "Bonus":
      new_doc = self.users.find_one_and_update(
        {"_id": recipient},
        {"$set": {"bonus": amount}},
        upsert=True,
        return_document=ReturnDocument.AFTER
      )

    await exp.check(new_doc, silent = True)
    await ctx.send(content=f"Successfully updated <@{recipient}>'s **{type}** experience to **{amount}**.",allowed_mentions=discord.AllowedMentions.none())

  @commands.slash_command(guild_ids=[GUILD])
  @commands.has_any_role(ADMIN_ROLE_ID, STAFF_ROLE_ID)
  async def award(self, ctx: ApplicationContext, 
                  recipient: Option(int, "ID of the user whose experience you'd like to edit", name="member_id", required=True, default=0),
                  amount: Option(int, "New value to set someone's experience to", name="amount", required=True, default=0),
                  type: Option(str, "Type of exp you'd like to award", name="type", required=True, choies=["Text", "Voice", "Bonus"], default="Text")
                  ):
    await ctx.response.defer()
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
    if type == "bonus":
      new_doc = self.users.find_one_and_update(
        {"_id": recipient},
        {"$set": {"bonus": (doc.get("bonus", 0) + amount)}},
        upsert=True,
        return_document=ReturnDocument.AFTER
      )

    await exp.check(new_doc, silent = True)
    await ctx.followup.send(content=f"Successfully added **{amount}** to <@{recipient}>'s **{type}** experience.",allowed_mentions=discord.AllowedMentions.none())

  @commands.slash_command(guild_ids=[GUILD])
  @commands.has_any_role(ADMIN_ROLE_ID, STAFF_ROLE_ID)
  async def config(self, ctx: ApplicationContext, 
                   action: Option(str, "Type of action you want to perform on a config", name="action", required=True, choies=["Add", "Edit", "Remove", "View", "Refresh"]), 
                   setting: Option(str, "Name of the config you are viewing/modifying", name="config_name", required=False, default=None), 
                   params: Option(str, "For editing/adding configs. Use `key=value` notation and separate keys/values with new lines", name="parameters", default=None)
                   ):

    await ctx.response.defer()
    collection = self.database.config
    action = action.lower()

    if action not in ["edit", "add", "remove", "view", "refresh"]:
      await ctx.followup.send("Invalid action. Use `edit`, `add`, `remove`, `view`, or `refresh`.")
      return

    if action == "view":
      import io
      if setting is None or setting == '':
        results = [doc['setting'] for doc in collection.find()]
        content = '\n'.join(results)
      else:
        result = collection.find_one({"setting": setting})
        if not result:
          await ctx.followup.send(f"Setting `{setting}` not found.")
          return
        content = '\n'.join([f"{k}={v}" for k, v in result['value'].items()]).replace('\\\\', '\\')
        content.replace('\'','')

      if len(content) > 1900:
        buffer = io.BytesIO(content.encode('utf-8'))
        file = discord.File(fp=buffer, filename=f'{setting}.txt')
        await ctx.followup.send(content='This config is too large to be output in a discord message, here is a text file instead:', file=file)
      else:
        await ctx.followup.send(f'# Previewing {setting if setting not in [None, ""] else "every"} config:\n```css\n{content}```')
      return

    if action == "remove":
      result = collection.delete_one({"setting": setting})
      if result.deleted_count > 0:
        self.refresh_databases()
        await ctx.followup.send(f"Successfully removed setting `{setting}`.")
      else:
        await ctx.followup.send(f"Setting `{setting}` not found.")
      return
    
    if action == "refresh":
      self.refresh_databases()
      await ctx.followup.send("Refreshed the database cache.")
      return

    if action in ["edit", "add"]:
      if not params and not attachment:
        await ctx.followup.send("Please provide parameters using triple backticks or upload a `.txt` file with `key=value` and `key=[value1, value2]` lines.")
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
          await ctx.followup.send(f"Setting `{setting}` already exists. Use `.config edit` to modify it.")
          return
        collection.insert_one({"setting": setting, "value": parameters})
        self.refresh_databases()
        await ctx.followup.send(f"Successfully added setting `{setting}`{new_parameters}")

      elif action == "edit":
        result = collection.update_one(
          {"setting": setting},
          {"$set": {"value": parameters}}
        )
        if result.matched_count > 0:
          self.refresh_databases()
          await ctx.followup.send(f"Successfully updated setting `{setting}`{new_parameters}")
        else:
          await ctx.followup.send(f"Setting `{setting}` not found. Use `.config add` to create it.")

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
    exp.update_database()
    for cog in self.bot.cogs.values():
      try:
        cog.update_database()
      except AttributeError:
        pass

  def uptime(self) -> str:
        now = discord.utils.utcnow()
        delta = now - self.start_time
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)

        fmt = "{h}h {m}m {s}s`"
        if days:
            fmt = "`{d}d " + fmt
        else:
          fmt = "`" + fmt

        return fmt.format(d=days, h=hours, m=minutes, s=seconds)
