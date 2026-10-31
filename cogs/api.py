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

import hmac
import hashlib
import secrets
import asyncio
from aiohttp import web

API_ENDPOINT = os.environ.get('API_ENDPOINT')
PORT = os.environ.get('API_PORT')

ADMIN_ROLE_ID = int(os.environ['ADMIN_ROLE_ID'])

class API(commands.Cog):
  def __init__(self, bot, mongo):
    self.bot = bot
    self.runner = None
    self.users = mongo.database.users
    self.recent = mongo.database.recent
    self.config = mongo.database.config
    self.api_keys = mongo.database.api_keys

  @commands.Cog.listener()
  async def on_ready(self):
    if self.runner is None:
      app = web.Application()
      app.add_routes([
                      web.post(f"{API_ENDPOINT}/award/", self.award_user),
                      web.get(f"{API_ENDPOINT}/user/{{id:\\d+}}", self.get_user)
                    ])
      self.runner = web.AppRunner(app)
      await self.runner.setup()
      site = web.TCPSite(self.runner, '0.0.0.0', int(PORT))
      await site.start()

  async def get_user(self, request: web.Request) -> web.Response:
    key = request.headers.get('Authorization', '').removeprefix('Bearer ')
    if not self.api_keys.find_one({"_id": (hashlib.sha256(key.encode()).hexdigest())}):
      return web.json_response({'error': 'unauthorized'}, status=401)

    recipient = int(request.match_info["id"])
    doc = self.users.find_one({"_id": recipient})
    if doc:
      return web.json_response(doc, status=200)
    else:
      return web.json_response(status=404)

  async def award_user(self, request: web.Request) -> web.Response:
    key = request.headers.get('Authorization', '').removeprefix('Bearer ')
    if not self.api_keys.find_one({"_id": (hashlib.sha256(key.encode()).hexdigest())}):
      return web.json_response({'error': 'unauthorized'}, status=401)

    try:
      payload = await request.json()
      recipient = int(payload["id"])
    except (ValueError, KeyError, TypeError):
      return web.json_response({'error': 'missing or malformed "id" field (recommended to send as a string)'}, status=400)

    award_type = payload.get("type")
    if not award_type:
      return web.json_response({'error': 'missing "type" field'}, status=400)
    amount = payload.get("amount", 0)
    doc = await exp.internal_award(recipient=recipient, amount=amount, type=award_type)
    if doc:
      doc["_id"] = str(doc["_id"])
      return web.json_response(text=json.dumps(doc, default=str), status=200)
    else:
      return web.json_response({"error": "invalid experience type"}, status=400)

  @commands.command()
  @commands.has_any_role(ADMIN_ROLE_ID)
  @commands.guild_only()
  async def apikey(self, ctx: commands.Context, action: str = None, label: str = None):
    if not label and action != "list":
      await ctx.send("Invalid command. Please provide a label after providing your action.")
      return
    if action == "create":
      key = secrets.token_urlsafe(32)
      try:
        await ctx.author.send(f"Your `{label}` API key you generated is: ||`{key}`||", delete_after=30)
      except discord.Forbidden:
        await ctx.send("Please open your DMs so you can receive an API key privately.")
        return
      self.api_keys.insert_one({"_id": (hashlib.sha256(key.encode()).hexdigest()), "label": label, "created": datetime.now(timezone.utc).isoformat()})
      await ctx.send(f"Created API key `{label}` and stored its SHA256 hash to the database. "
                     f"Your key was sent via DM, the message will be auto-deleted after 30 seconds. "
                     f"__You will not be able to view this key again, please keep it safe__.")
    elif action == "remove":
      found = self.api_keys.find_one_and_delete({"label": label})
      if found:
        await ctx.send(f"Removed API key `{label}`.")
      else:
        await ctx.send(f"Could not find API key with label `{label}`")
    elif action == "view":
      found = self.api_keys.find_one({"label": label})
      if found:
        await ctx.send(f"API key `{label}` created at <t:{int(datetime.fromisoformat(found.get('created')).timestamp())}:F>, SHA256 hash of this key begins with `{found['_id'][0:7]}`. (For security, the original key is neither stored nor recoverable)")
      else:
        await ctx.send(f"Could not find API key with label `{label}`")
      return
    elif action == "list":
      keys = [k for k in self.api_keys.find()]
      if not keys:
        await ctx.send("No keys have been created yet.")
        return
      result = "\n".join(f"- `{k.get('label')}` (Created <t:{int(datetime.fromisoformat(k.get('created')).timestamp())}:F>): Key hash starts with `{(k.get('_id'))[0:7]}...`" for k in keys)
      await ctx.send(f"Active keys are:\n{result}\n(For security, the original keys are neither stored nor recoverable)")
    else:
      await ctx.send(f"Invalid command. Formatting is `{self.bot.command_prefix}apikey [create/remove/view] [api key name]` or `{self.bot.command_prefix}apikey list` to view all active keys.")
