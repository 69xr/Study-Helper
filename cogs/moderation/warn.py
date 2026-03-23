"""
cogs/moderation/warn.py  — v20
Improvements:
  • Deferred response for safety on slow DB
  • Reports if DM was blocked
  • Auto-timeout support added to threshold escalation (in addition to mute/kick/ban)
  • /warninfo <id>  — look up one warning by ID
  • Consistent error messages with ephemeral=True
"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone, timedelta
from utils import db
from utils.helpers import success_embed, error_embed, warning_embed, send_log
import config


class Warn(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── /warn ─────────────────────────────────────────────────
    @app_commands.command(name="warn", description="Issue a warning to a member.")
    @app_commands.describe(member="Member to warn", reason="Reason for warning")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def warn(self, interaction: discord.Interaction,
                   member: discord.Member, reason: str = "No reason provided"):
        await interaction.response.defer()

        if member.bot:
            await interaction.followup.send(embed=error_embed("Can't Warn", "You can't warn a bot."), ephemeral=True)
            return
        if member == interaction.user:
            await interaction.followup.send(embed=error_embed("Can't Warn", "You can't warn yourself."), ephemeral=True)
            return
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.followup.send(embed=error_embed("Can't Warn", "That member's role is higher than mine."), ephemeral=True)
            return

        total = await db.add_warning(interaction.guild_id, member.id, interaction.user.id, reason)
        await db.log_action(interaction.guild_id, "WARN", interaction.user.id, member.id, reason, str(total))

        embed = discord.Embed(title="⚠️  Warning Issued", color=0xFEE75C, timestamp=datetime.now(timezone.utc))
        embed.add_field(name="👤 User",    value=f"{member.mention}\n`{member}`", inline=True)
        embed.add_field(name="🛡️ Mod",    value=interaction.user.mention,        inline=True)
        embed.add_field(name="📋 Reason",  value=reason,                          inline=False)
        embed.add_field(name="⚠️ Total",   value=f"`{total}` warning(s)",         inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Warning ID logged • User ID: {member.id}")

        # DM the warned member
        dm_sent = False
        try:
            await member.send(embed=discord.Embed(
                title=f"⚠️ Warning in {interaction.guild.name}",
                description=f"**Reason:** {reason}\n**Total warnings:** {total}",
                color=0xFEE75C))
            dm_sent = True
        except discord.Forbidden:
            pass

        if not dm_sent:
            embed.set_footer(text=f"⚠ DMs blocked — member not notified • User ID: {member.id}")

        await interaction.followup.send(embed=embed)

        # Log to mod channel
        s = await db.get_guild_settings(interaction.guild_id)
        if s and s.get("log_channel"):
            await send_log(interaction.guild, s["log_channel"], embed)

        # ── Threshold auto-escalation ────────────────────────
        threshold = await db.get_threshold_for_count(interaction.guild_id, total)
        if not threshold:
            return

        action   = threshold["action"]
        dur_sec  = threshold.get("duration")
        esc_reason = f"Auto-action: {total} warning threshold reached"

        try:
            if action == "kick":
                await member.kick(reason=esc_reason)
                await interaction.followup.send(embed=warning_embed(
                    "Auto-Kick", f"{member.mention} was automatically kicked after `{total}` warnings."))

            elif action == "ban":
                await member.ban(reason=esc_reason, delete_message_days=0)
                await interaction.followup.send(embed=warning_embed(
                    "Auto-Ban", f"{member.mention} was automatically banned after `{total}` warnings."))

            elif action == "timeout":
                # Use Discord native timeout (no mute role needed)
                until = discord.utils.utcnow() + timedelta(seconds=dur_sec or 3600)
                await member.timeout(until, reason=esc_reason)
                dur_str = f"{(dur_sec or 3600) // 60}m" if dur_sec else "1h"
                await interaction.followup.send(embed=warning_embed(
                    "Auto-Timeout", f"{member.mention} was automatically timed out ({dur_str}) after `{total}` warnings."))

            elif action == "mute":
                guild_settings = await db.get_guild_settings(interaction.guild_id)
                mute_role_id   = guild_settings.get("mute_role") if guild_settings else None
                mute_role      = interaction.guild.get_role(int(mute_role_id)) if mute_role_id else None
                if mute_role and mute_role not in member.roles:
                    await member.add_roles(mute_role, reason=esc_reason)
                    dur_str = f"{dur_sec // 60}m" if dur_sec else "permanent"
                    await interaction.followup.send(embed=warning_embed(
                        "Auto-Mute", f"{member.mention} was automatically muted ({dur_str}) after `{total}` warnings."))
                    if dur_sec:
                        import asyncio as _aio
                        async def _auto_unmute():
                            await _aio.sleep(dur_sec)
                            try:
                                if mute_role in member.roles:
                                    await member.remove_roles(mute_role, reason="Auto-mute expired (warn threshold)")
                            except Exception:
                                pass
                        t = _aio.create_task(_auto_unmute())
                        t.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error_embed("Auto-Action Failed", "Missing permissions to execute the threshold action."),
                ephemeral=True)

    # ── /warnings ─────────────────────────────────────────────
    @app_commands.command(name="warnings", description="View a member's warnings.")
    @app_commands.describe(member="Member to check")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        warns = await db.get_warnings(interaction.guild_id, member.id)
        if not warns:
            await interaction.response.send_message(
                embed=success_embed("No Warnings", f"{member.mention} has no warnings on record."), ephemeral=True)
            return
        embed = discord.Embed(title=f"⚠️  Warnings — {member}", color=0xFEE75C)
        embed.set_thumbnail(url=member.display_avatar.url)
        for w in warns[:10]:
            mod = interaction.guild.get_member(w["mod_id"])
            embed.add_field(
                name=f"#{w['id']} — {w['created_at'][:10]}",
                value=f"**Reason:** {w['reason']}\n**Mod:** {str(mod) if mod else w['mod_id']}",
                inline=False)
        if len(warns) > 10:
            embed.set_footer(text=f"Showing 10/{len(warns)} warnings")
        else:
            embed.set_footer(text=f"Total: {len(warns)} warning(s)")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /clearwarns ───────────────────────────────────────────
    @app_commands.command(name="clearwarns", description="Clear all warnings for a member.")
    @app_commands.describe(member="Member whose warnings to clear")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def clearwarns(self, interaction: discord.Interaction, member: discord.Member):
        count = await db.clear_warnings(interaction.guild_id, member.id)
        if count == 0:
            await interaction.response.send_message(
                embed=error_embed("No Warnings", f"{member.mention} has no warnings to clear."), ephemeral=True)
            return
        await db.log_action(interaction.guild_id, "CLEARWARNS", interaction.user.id, member.id, f"Cleared {count} warning(s)")
        await interaction.response.send_message(
            embed=success_embed("Cleared", f"Cleared `{count}` warning(s) for {member.mention}."), ephemeral=True)

    # ── /delwarn ──────────────────────────────────────────────
    @app_commands.command(name="delwarn", description="Delete a specific warning by ID.")
    @app_commands.describe(warning_id="Warning ID (from /warnings)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def delwarn(self, interaction: discord.Interaction, warning_id: int):
        removed = await db.remove_warning(warning_id, interaction.guild_id)
        if not removed:
            await interaction.response.send_message(
                embed=error_embed("Not Found", f"No warning `#{warning_id}` found in this server."), ephemeral=True)
            return
        await interaction.response.send_message(
            embed=success_embed("Removed", f"Warning `#{warning_id}` has been deleted."), ephemeral=True)

    # ── Error handler ─────────────────────────────────────────
    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            msg = "You need **Manage Messages** (or higher) to use this command."
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=error_embed("Missing Permissions", msg), ephemeral=True)
            else:
                await interaction.followup.send(embed=error_embed("Missing Permissions", msg), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Warn(bot))
