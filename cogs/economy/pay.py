import discord
from discord import app_commands
from discord.ext import commands
from utils import db

CURRENCY = "🪙"

class Pay(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="pay", description="Transfer coins to another user.")
    @app_commands.describe(user="Who to pay", amount="Amount to transfer")
    async def pay(self, interaction: discord.Interaction,
                  user: discord.Member, amount: app_commands.Range[int, 1, 1_000_000]):
        if user.id == interaction.user.id:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ You can't pay yourself.", color=0xED4245), ephemeral=True)
            return
        if user.bot:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ You can't pay a bot.", color=0xED4245), ephemeral=True)
            return
        ok = await db.transfer_coins(interaction.guild_id, interaction.user.id, user.id, amount)
        if not ok:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ You don't have `{amount:,}` {CURRENCY}.", color=0xED4245),
                ephemeral=True)
            return
        embed = discord.Embed(title=f"{CURRENCY} Transfer Complete", color=0x3dffaa)
        embed.add_field(name="From",   value=interaction.user.mention, inline=True)
        embed.add_field(name="To",     value=user.mention,             inline=True)
        embed.add_field(name="Amount", value=f"`{amount:,}` {CURRENCY}", inline=True)
        await interaction.response.send_message(embed=embed)

async def setup(bot): await bot.add_cog(Pay(bot))
