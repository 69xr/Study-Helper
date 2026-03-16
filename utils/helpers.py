"""
utils/helpers.py  —  Shared embed builders and utility functions
"""
import discord
from config import Colors
from datetime import datetime, timezone


def success_embed(title: str, description: str = "", footer: str = "") -> discord.Embed:
    e = discord.Embed(title=f"✅  {title}", description=description, color=Colors.SUCCESS)
    if footer:
        e.set_footer(text=footer)
    return e


def error_embed(title: str, description: str = "") -> discord.Embed:
    return discord.Embed(title=f"❌  {title}", description=description, color=Colors.ERROR)


def warning_embed(title: str, description: str = "") -> discord.Embed:
    return discord.Embed(title=f"⚠️  {title}", description=description, color=Colors.WARNING)


def info_embed(title: str, description: str = "", footer: str = "") -> discord.Embed:
    e = discord.Embed(title=f"ℹ️  {title}", description=description, color=Colors.INFO)
    if footer:
        e.set_footer(text=footer)
    return e


def mod_embed(action: str, target: discord.Member, moderator: discord.Member, reason: str, color: int) -> discord.Embed:
    e = discord.Embed(title=action, color=color, timestamp=datetime.now(timezone.utc))
    e.add_field(name="👤 User",   value=f"{target.mention}\n`{target}`", inline=True)
    e.add_field(name="🛡️ Mod",   value=f"{moderator.mention}\n`{moderator}`", inline=True)
    e.add_field(name="📋 Reason", value=reason, inline=False)
    e.set_thumbnail(url=target.display_avatar.url)
    e.set_footer(text=f"User ID: {target.id}")
    return e


def parse_hex_color(hex_str: str, fallback: int = Colors.PRIMARY) -> int:
    try:
        return int(hex_str.lstrip("#"), 16)
    except (ValueError, AttributeError):
        return fallback


async def send_log(guild: discord.Guild, log_channel_id: int | None, embed: discord.Embed) -> None:
    """Send an embed to the guild's log channel if set."""
    if not log_channel_id:
        return
    channel = guild.get_channel(log_channel_id)
    if channel and isinstance(channel, discord.TextChannel):
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass
