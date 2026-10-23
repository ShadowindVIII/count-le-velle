import discord

from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi

import io
import os
import dotenv

class OptOut(discord.ui.View):
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

