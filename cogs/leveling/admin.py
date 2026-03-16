import discord
from discord import app_commands
from discord.ext import commands
from utils import db
from utils.helpers import success_embed, error_embed
import aiosqlite, config

class LevelingAdmin(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="setxp", description="[Admin] Set a user's XP directly.")
    @app_commands.describe(user="Target user", xp="XP amount to set (0–1,000,000)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setxp(self, interaction: discord.Interaction,
                     user: discord.Member,
                     xp: app_commands.Range[int, 0, 1000000]):
        # Calculate level from XP
        def xp_for_level(n): return 5*(n**2) + 50*n + 100
        level = 0
        remaining = xp
        while remaining >= xp_for_level(level + 1):
            remaining -= xp_for_level(level + 1)
            level += 1

        async with aiosqlite.connect(config.DB_PATH) as db_conn:
            await db_conn.execute("INSERT OR IGNORE INTO levels (guild_id,user_id) VALUES (?,?)",
                                   (interaction.guild_id, user.id))
            await db_conn.execute(
                "UPDATE levels SET xp=?, level=? WHERE guild_id=? AND user_id=?",
                (remaining, level, interaction.guild_id, user.id))
            await db_conn.commit()

        embed = success_embed("XP Set")
        embed.add_field(name="User",  value=user.mention, inline=True)
        embed.add_field(name="XP",    value=f"`{xp:,}`",  inline=True)
        embed.add_field(name="Level", value=f"`{level}`",  inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=error_embed("Missing Permissions"), ephemeral=True)

async def setup(bot): await bot.add_cog(LevelingAdmin(bot))
