"""
utils/helpers.py — Severus Bot embed builders & utilities
All embeds share consistent branding, colors, and footer.
"""
import discord
from datetime import datetime, timezone
import config


def parse_hex_color(value: str, default: int = 0x5865F2) -> int:
    """Parse a hex color string like #FF5733 or FF5733 to an int."""
    try:
        return int(value.strip().lstrip("#"), 16)
    except (ValueError, AttributeError):
        return default


def _footer(embed: discord.Embed, user: discord.User | discord.Member | None = None):
    """Apply consistent Severus branding footer."""
    text = config.FOOTER_TEXT
    if user:
        text = f"Requested by {user} • {config.FOOTER_TEXT}"
    icon = config.FOOTER_ICON or None
    embed.set_footer(text=text, icon_url=icon)
    embed.timestamp = datetime.now(timezone.utc)
    return embed


def base_embed(title: str = "", description: str = "",
               color: int = None) -> discord.Embed:
    """Base embed with branding."""
    e = discord.Embed(
        title=title,
        description=description,
        color=color or config.Colors.PRIMARY
    )
    return _footer(e)


def success_embed(title: str, description: str = "") -> discord.Embed:
    e = discord.Embed(
        title=f"✅  {title}",
        description=description,
        color=config.Colors.SUCCESS
    )
    return _footer(e)


def error_embed(title: str, description: str = "") -> discord.Embed:
    e = discord.Embed(
        title=f"❌  {title}",
        description=description,
        color=config.Colors.ERROR
    )
    return _footer(e)


def warning_embed(title: str, description: str = "") -> discord.Embed:
    e = discord.Embed(
        title=f"⚠️  {title}",
        description=description,
        color=config.Colors.WARN
    )
    return _footer(e)


def info_embed(title: str, description: str = "") -> discord.Embed:
    e = discord.Embed(
        title=f"ℹ️  {title}",
        description=description,
        color=config.Colors.INFO
    )
    return _footer(e)


def mod_embed(action: str, target: discord.Member,
              moderator: discord.Member, reason: str,
              color: int = None) -> discord.Embed:
    """Moderation action embed — consistent layout for all mod actions."""
    e = discord.Embed(
        title=action,
        color=color or config.Colors.MOD
    )
    e.set_thumbnail(url=target.display_avatar.url)
    e.add_field(name="👤 Target",     value=f"{target.mention}\n`{target}` (`{target.id}`)", inline=True)
    e.add_field(name="🛡️ Moderator", value=moderator.mention,                                inline=True)
    e.add_field(name="📋 Reason",     value=reason,                                           inline=False)
    return _footer(e, moderator)


def music_embed(title: str, description: str = "",
                thumbnail: str = None) -> discord.Embed:
    """Music-specific embed with Spotify-green color."""
    e = discord.Embed(
        title=title,
        description=description,
        color=config.Colors.MUSIC
    )
    if thumbnail:
        e.set_thumbnail(url=thumbnail)
    return _footer(e)


async def send_log(guild: discord.Guild, channel_id: int,
                   embed: discord.Embed) -> None:
    """Send embed to the guild's log channel."""
    if not channel_id:
        return
    ch = guild.get_channel(int(channel_id))
    if not ch:
        return
    try:
        await ch.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass
