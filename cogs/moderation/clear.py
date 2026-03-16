import discord
from discord import app_commands
from discord.ext import commands
from utils.helpers import success_embed, error_embed

class Clear(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="clear", description="Delete messages from this channel.")
    @app_commands.describe(amount="Number of messages to delete (1-100)", user="Only delete messages from this user")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction,
                    amount: app_commands.Range[int, 1, 100] = 10,
                    user: discord.Member = None):
        await interaction.response.defer(ephemeral=True)
        check = (lambda m: m.author == user) if user else None
        deleted = await interaction.channel.purge(limit=amount, check=check)
        await interaction.followup.send(
            embed=success_embed("Cleared", f"Deleted `{len(deleted)}` message(s)."), ephemeral=True)

    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=error_embed("Missing Permissions"), ephemeral=True)

async def setup(bot): await bot.add_cog(Clear(bot))
