import discord

class RevealButton(discord.ui.View):
  def __init__(self, content=None, embed=None, timeout=60):
    super().__init__(timeout=timeout, disable_on_timeout=True)
    self.content = content
    self.embed = embed
  
  @discord.ui.button(label='Show to everyone', style=discord.ButtonStyle.gray)
  async def reveal_button(self, button: discord.ui.Button, interaction: discord.Interaction):
    self.disable_all_items()
    await interaction.channel.send(content=self.content, embed=self.embed)
    await interaction.response.edit_message(view=self, delete_after=0)

  async def on_timeout(self: discord.ui.View):
    try:
      self.disable_all_items()
      await self.message.edit(view=self)
    except Exception:
      pass
