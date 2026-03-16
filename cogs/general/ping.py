import discord
from discord import app_commands
from discord.ext import commands

class Ping(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="ping", description="Check the bot's latency.")
    async def ping(self, interaction: discord.Interaction):
        ms = round(self.bot.latency * 1000)
        color = 0x57F287 if ms < 100 else (0xFEE75C if ms < 200 else 0xED4245)
        emoji = "🟢" if ms < 100 else ("🟡" if ms < 200 else "🔴")
        status = "`Excellent`" if ms < 100 else ("`Good`" if ms < 200 else "`High`")
        embed = discord.Embed(title=f"{emoji} Pong!", color=color)
        embed.add_field(name="WebSocket", value=f"`{ms} ms`", inline=True)
        embed.add_field(name="Status",    value=status,        inline=True)
        embed.set_footer(text=f"Requested by {interaction.user}", icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

async def setup(bot): await bot.add_cog(Ping(bot))
