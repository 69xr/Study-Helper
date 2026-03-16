import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
from utils import db
from utils.helpers import success_embed, error_embed, warning_embed, send_log
import config

class Warn(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="warn", description="Issue a warning to a member.")
    @app_commands.describe(member="Member to warn", reason="Reason for warning")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def warn(self, interaction: discord.Interaction,
                   member: discord.Member, reason: str = "No reason provided"):
        if member.bot:
            await interaction.response.send_message(embed=error_embed("Can't Warn", "You can't warn a bot."), ephemeral=True)
            return
        total = await db.add_warning(interaction.guild_id, member.id, interaction.user.id, reason)
        await db.log_action(interaction.guild_id, "WARN", interaction.user.id, member.id, reason, str(total))
        embed = discord.Embed(title="⚠️  Warning Issued", color=0xFEE75C, timestamp=datetime.now(timezone.utc))
        embed.add_field(name="👤 User",   value=f"{member.mention}\n`{member}`", inline=True)
        embed.add_field(name="🛡️ Mod",   value=interaction.user.mention,        inline=True)
        embed.add_field(name="📋 Reason", value=reason,                          inline=False)
        embed.add_field(name="⚠️ Total",  value=f"`{total}` warning(s)",         inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"User ID: {member.id}")
        await interaction.response.send_message(embed=embed)
        try:
            await member.send(embed=discord.Embed(
                title=f"⚠️ Warning in {interaction.guild.name}",
                description=f"**Reason:** {reason}\n**Total:** {total} warning(s)",
                color=0xFEE75C))
        except discord.Forbidden:
            pass
        s = await db.get_guild_settings(interaction.guild_id)
        if s and s.get("log_channel"):
            await send_log(interaction.guild, s["log_channel"], embed)
        if total >= config.MAX_WARNS_BEFORE_KICK:
            kicked = False
            try:
                await member.kick(reason=f"Auto-kick: {total} warnings reached")
                kicked = True
            except discord.Forbidden:
                pass
            if kicked:
                try:
                    await interaction.followup.send(embed=warning_embed(
                        "Auto-Kick", f"{member.mention} was auto-kicked after `{total}` warnings."))
                except Exception:
                    pass

    @app_commands.command(name="warnings", description="View a member's warnings.")
    @app_commands.describe(member="Member to check")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        warns = await db.get_warnings(interaction.guild_id, member.id)
        if not warns:
            await interaction.response.send_message(
                embed=success_embed("No Warnings", f"{member.mention} has no warnings."), ephemeral=True)
            return
        embed = discord.Embed(title=f"⚠️  Warnings — {member}", color=0xFEE75C)
        embed.set_thumbnail(url=member.display_avatar.url)
        for w in warns[:10]:
            mod = interaction.guild.get_member(w["mod_id"])
            embed.add_field(
                name=f"#{w['id']} — {w['created_at'][:10]}",
                value=f"**Reason:** {w['reason']}\n**Mod:** {str(mod) if mod else w['mod_id']}",
                inline=False)
        embed.set_footer(text=f"Total: {len(warns)} warning(s)")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="clearwarns", description="Clear all warnings for a member.")
    @app_commands.describe(member="Member whose warnings to clear")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clearwarns(self, interaction: discord.Interaction, member: discord.Member):
        count = await db.clear_warnings(interaction.guild_id, member.id)
        if count == 0:
            await interaction.response.send_message(
                embed=error_embed("No Warnings", f"{member.mention} had no warnings."), ephemeral=True)
            return
        await interaction.response.send_message(
            embed=success_embed("Cleared", f"Cleared `{count}` warning(s) for {member.mention}."), ephemeral=True)

    @app_commands.command(name="delwarn", description="Delete a specific warning by ID.")
    @app_commands.describe(warning_id="Warning ID (from /warnings)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def delwarn(self, interaction: discord.Interaction, warning_id: int):
        removed = await db.remove_warning(warning_id, interaction.guild_id)
        if not removed:
            await interaction.response.send_message(
                embed=error_embed("Not Found", f"No warning `#{warning_id}` in this server."), ephemeral=True)
            return
        await interaction.response.send_message(
            embed=success_embed("Removed", f"Warning `#{warning_id}` deleted."), ephemeral=True)

    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=error_embed("Missing Permissions"), ephemeral=True)

async def setup(bot): await bot.add_cog(Warn(bot))
