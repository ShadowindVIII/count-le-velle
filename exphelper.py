import discord

from pymongo.mongo_client import MongoClient

import os
import asyncio

def init(inputBot, mongo: MongoClient):
  global config, bot, users
  config = mongo.database.config
  users = mongo.database.users
  bot = inputBot
  update_database()

async def on_ready():
  global guild
  guild = await bot.fetch_guild(int(os.environ["OPERATING_GUILD"])) 
    
def update_database():
  global roles, immune_roles
  roles = [(int(doc["value"]["threshold"]),int(doc["value"]["role_id"]),doc["value"]["role_name"],doc["value"]["message"],doc["value"]["persistent"]=="True") for doc in config.find({"setting": {"$regex": "^reward_"}})]
  roles.sort(key=lambda t: t[0])
  immune_roles = config.find_one({"setting": "immune_roles"})["value"]["list"]
    

async def check(doc):
  if guild is None:
    await asyncio.sleep(1)
  user = await guild.fetch_member(doc["_id"])
  total_exp = doc.get("text", 0) + doc.get("voice", 0)

  level = 0
  needed_exp = 100
  while total_exp >= needed_exp:
    level += 1
    needed_exp += 5 * level**2 + 50 * level + 100
  current_level = level

  prev_level = doc.get("level")
  if prev_level != current_level:
    users.update_one({"_id": doc["_id"]}, {"$set": {"level": current_level}})
    if prev_level is not None and current_level > prev_level:
      try:
        await user.send(f"Congratulations **{user.nick or user.display_name}**, you just advanced to **level {current_level}**!")
      except discord.Forbidden:
        pass

  eligible = [t for t in roles if current_level >= t[0]]
  if not eligible:
    return

  pref_id = doc.get("preference")
  pref = next((t for t in eligible if t[1] == pref_id), None)
  target = pref or max(eligible, key=lambda t: t[0])

  role = guild.get_role(target[1])
  if not role:
    role = await guild.fetch_role(target[1])

  level_role_ids = {t[1] for t in roles if not t[4]}
  to_remove = [r for r in user.roles if r.id in level_role_ids and r.id != role.id]
  if to_remove:
    await user.remove_roles(*to_remove)

  if role not in user.roles:
    await user.add_roles(role)
    if not pref:
      try:
        await user.send(target[3].strip("\"").replace("\\n","\n"))
      except discord.Forbidden:
        pass

def exp_for_level(n: int = 0):
  if n <= 0:
    return 0
  return 5 * (n * (n - 1) * (2 * n - 1) // 6) + 25 * n * (n - 1) + 100 * n