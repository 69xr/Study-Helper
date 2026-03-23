"""
cogs/moderation/timeout.py
/timeout — uses Discord's native timeout (communicate_disabled_until).
Cleaner than mute role — no role needed, works on any server.
"""
import discord, re
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone, timedelta
from utils import db
from utils.helpers import mod_embed, error_embed, send_log
import config

def parse_duration(s: str) -> int | None:
    total = 0
    for num, unit in re.findall(r"(\d+)([smhd])", s.lower()):
        n = int(num)
        if unit == "s": total += n
        elif unit == "m": total += n * 60
        elif unit == "h": total += n * 3600
        elif unit == "d": total += n * 86400
    return total if total > 0 else None


class Timeout(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="timeout",
                          description="Timeout a member using Discord's native system (no role needed).")
    @app_commands.describe(
        member="Member to timeout",
        duration="Duration: 30s, 10m, 1h, 1d (max 28d)",
        reason="Reason for timeout"
    )
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout(self, interaction: discord.Interaction,
                      member: discord.Member,
                      duration: str = "10m",
                      reason: str = "No reason provided"):
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                embed=error_embed("Can't Timeout", "That member's role is too high."), ephemeral=True)
            return
        if member == interaction.user:
            await interaction.response.send_message(
                embed=error_embed("Can't Timeout", "You can't timeout yourself."), ephemeral=True)
            return
        if member.guild_permissions.administrator:
            await interaction.response.send_message(
                embed=error_embed("Can't Timeout", "Administrators cannot be timed out."), ephemeral=True)
            return

        secs = parse_duration(duration)
        if not secs:
            await interaction.response.send_message(
                embed=error_embed("Invalid Duration",
                    "Use format like `30s`, `10m`, `1h`, `1d`.\nMaximum: 28 days."),
                ephemeral=True)
            return
        if secs > 28 * 86400:
            await interaction.response.send_message(
                embed=error_embed("Too Long", "Maximum timeout duration is 28 days."), ephemeral=True)
            return

        until = datetime.now(timezone.utc) + timedelta(seconds=secs)
        try:
            await member.timeout(until, reason=f"{interaction.user}: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=error_embed("No Permission", "I can't timeout that member."), ephemeral=True)
            return

        # Format duration nicely
        parts = []
        if secs >= 86400: parts.append(f"{secs // 86400}d")
        if (secs % 86400) >= 3600: parts.append(f"{(secs % 86400) // 3600}h")
        if (secs % 3600) >= 60: parts.append(f"{(secs % 3600) // 60}m")
        if secs % 60: parts.append(f"{secs % 60}s")
        dur_str = " ".join(parts)

        embed = mod_embed(f"⏱️  Member Timed Out", member, interaction.user, reason, config.Colors.WARN)
        embed.add_field(name="Duration", value=f"`{dur_str}`",                         inline=True)
        embed.add_field(name="Expires",  value=f"<t:{int(until.timestamp())}:R>",      inline=True)
        await interaction.response.send_message(embed=embed)

        # DM the member
        try:
            dm = discord.Embed(
                title=f"⏱️ You were timed out in **{interaction.guild.name}**",
                description=f"**Duration:** `{dur_str}`\n**Reason:** {reason}\n**Expires:** <t:{int(until.timestamp())}:R>",
                color=config.Colors.WARN)
            await member.send(embed=dm)
        except Exception:
            pass

        await db.log_action(interaction.guild_id, "TIMEOUT", interaction.user.id, member.id, reason, dur_str)
        s = await db.get_guild_settings(interaction.guild_id)
        if s:
            log_ch = s.get("log_mod_actions") or s.get("log_channel")
            if log_ch:
                await send_log(interaction.guild, log_ch, embed)

    @app_commands.command(name="untimeout", description="Remove a timeout from a member.")
    @app_commands.describe(member="Member to un-timeout", reason="Reason")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def untimeout(self, interaction: discord.Interaction,
                         member: discord.Member,
                         reason: str = "No reason provided"):
        if not member.is_timed_out():
            await interaction.response.send_message(
                embed=error_embed("Not Timed Out", f"{member.mention} is not currently timed out."),
                ephemeral=True)
            return
        await member.timeout(None, reason=f"{interaction.user}: {reason}")
        embed = discord.Embed(
            title="✅  Timeout Removed",
            description=f"{member.mention} (`{member}`) can now send messages again.",
            color=config.Colors.SUCCESS)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="Reason",    value=reason,                   inline=True)
        embed.set_footer(text=config.FOOTER_TEXT)
        await interaction.response.send_message(embed=embed)
        await db.log_action(interaction.guild_id, "UNTIMEOUT", interaction.user.id, member.id, reason)

    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=error_embed("Missing Permissions",
                        "You need **Moderate Members** permission to use timeout."),
                    ephemeral=True)


async def setup(bot): await bot.add_cog(Timeout(bot))
