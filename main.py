from discord.ext import commands
import discord
import os
from dotenv import load_dotenv
import traceback
import time
import asyncio
from cogs.admin import Admin
from cogs.text import Text
from cogs.voice import Voice
from cogs.publiccommands import PublicCommands
from cogs.api import API
import exphelper as exp
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import random
from datetime import datetime, timedelta

intents = discord.Intents()
intents.message_content = True
intents.messages = True
intents.guilds = True
intents.members = True
intents.voice_states = True

load_dotenv()

mongo = MongoClient(os.environ['MONGO_TOKEN'], tz_aware=True)
try:
  start_time = time.perf_counter()
  mongo.admin.command('ping')
  latency_ms = (time.perf_counter() - start_time) * 1000

  print("Pinged your deployment. You successfully connected to MongoDB!")
except Exception as e:
  print(e)


bot = commands.Bot(command_prefix=os.environ['PREFIX'], intents=intents)
bot.remove_command('help')

exp.init(bot, mongo)

bot.add_cog(Text(bot, mongo))
bot.add_cog(Voice(bot, mongo))
bot.add_cog(PublicCommands(bot, mongo))
bot.add_cog(Admin(bot, mongo))
if os.environ['API_ENDPOINT'] != "/path/to/your/api":
  bot.add_cog(API(bot, mongo))
else:
  print("API endpoint not specified, API cog will remain disabled under assumption it is not needed.")

# **************
# **************
# ERROR HANDLING
# **************
# **************

@bot.event
async def on_error(event_name, *args, **kwargs):
  err = traceback.format_exc()
  try:
    float(err)
    await print_error(f"float coming from on_error, {err}")
  except ValueError:
    await print_error(err)

@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
  await print_error(f"original message: {ctx.message.content}\n error: {error}")

@bot.event
async def on_application_command_error(ctx: commands.Context, error: commands.CommandError):
  if isinstance(error, commands.CommandOnCooldown):
    return #(already handled in cogs/publiccommands.py)
  await print_error(f"application command error: {error}")

async def print_error(error_string: str):
  if error_string[-13:-1] == ' is not foun':
    return
  logbook_channel = await bot.fetch_channel(os.environ['LOG_CHANNEL'])
  
  if len(error_string) <= 3900:
    embed = discord.Embed(title="Error Log", description=f'```{error_string}```', color=0xA9BFBE)
    await logbook_channel.send(embed=embed)
    return
  
  parts = []
  current_part = ""
  
  for line in error_string.split('\n'):
    if len(current_part) + len(line) + 1 > 3900:
      parts.append(current_part)
      current_part = line
    else:
      current_part += '\n' + line if current_part else line
  
  if current_part:
    parts.append(current_part)
  
  for i, part in enumerate(parts):
    embed = discord.Embed(title=f"Error Log (Part `{i + 1}`/`{len(parts)}`)", description=f'```{part}```', color=0xA9BFBE)
    await logbook_channel.send(embed=embed)

# For emergencies only 
@bot.command()
@commands.has_permissions(administrator=True)
async def crash(ctx: commands.Context):
  await ctx.send("done")
  await bot.close()

@bot.event
async def on_ready():
  await exp.on_ready()
  print(f'\n\n************************ READY ************************\n\n* COGS:\n{list(bot.cogs)}', flush=True)

  log_channel = await bot.fetch_channel(os.environ['LOG_CHANNEL'])
  status = os.environ['STATUS']
  #with open('startup_info.txt', encoding='UTF-8') as ident:
  #  startup_info = ident.readlines()
  #  status = (startup_info[1]).strip()
  #  await bot.change_presence(activity=discord.CustomActivity(name=status))
  await bot.change_presence(activity=discord.CustomActivity(name=status))
  embed = discord.Embed(title='\\*Hm?! Who goes there...?\\*', color=int(0xAAAAAA), description=f"""
Who dares disturb my slumber on this wretched day?!
Status: {status}
My latency: `{round(bot.latency * 1000)}` ms""")

  #  embed.set_footer(text=f'Identifier: {startup_info[0]}')
  await log_channel.send(embed=embed)
  

bot.run(os.environ['DISCORD_TOKEN'])
