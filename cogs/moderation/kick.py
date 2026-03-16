import discord
from discord import app_commands
from discord.ext import commands
from utils import db
from utils.helpers import mod_embed, error_embed, warning_embed, send_log
import config

class Kick(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="kick", description="Kick a member from the server.")
    @app_commands.describe(member="Member to kick", reason="Reason for kick")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction,
                   member: discord.Member, reason: str = "No reason provided"):
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                embed=error_embed("Can't Kick", "That member's role is too high for me to kick."), ephemeral=True)
            return
        if member == interaction.user:
            await interaction.response.send_message(
                embed=error_embed("Can't Kick", "You can't kick yourself."), ephemeral=True)
            return
        try:
            await member.send(embed=warning_embed(f"Kicked from {interaction.guild.name}", f"**Reason:** {reason}"))
        except discord.Forbidden:
            pass
        await member.kick(reason=f"{interaction.user}: {reason}")
        await db.log_action(interaction.guild_id, "KICK", interaction.user.id, member.id, reason)
        embed = mod_embed("👢  Member Kicked", member, interaction.user, reason, 0xFEE75C)
        await interaction.response.send_message(embed=embed)
        s = await db.get_guild_settings(interaction.guild_id)
        if s and s.get("log_channel"):
            await send_log(interaction.guild, s["log_channel"], embed)

    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=error_embed("Missing Permissions"), ephemeral=True)

async def setup(bot): await bot.add_cog(Kick(bot))
