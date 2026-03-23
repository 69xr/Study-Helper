"""
cogs/logging/logger.py
Comprehensive logging: message edits/deletes, member join/leave,
voice state, role changes, nickname changes, mod actions.
Each event type has its own configurable log channel.
"""
import discord
from discord.ext import commands
from datetime import datetime, timezone
import config

def _ts() -> str:
    return f"<t:{int(datetime.now(timezone.utc).timestamp())}:F>"

def _log_embed(title: str, description: str, color: int,
               fields: list[tuple] = None, thumbnail: str = None) -> discord.Embed:
    e = discord.Embed(title=title, description=description, color=color,
                      timestamp=datetime.now(timezone.utc))
    e.set_footer(text=config.FOOTER_TEXT)
    if fields:
        for name, val, inline in fields:
            e.add_field(name=name, value=str(val)[:1024], inline=inline)
    if thumbnail:
        e.set_thumbnail(url=thumbnail)
    return e

async def _send(guild: discord.Guild, channel_id: int | None, embed: discord.Embed):
    if not channel_id:
        return
    ch = guild.get_channel(int(channel_id))
    if not ch:
        return
    try:
        await ch.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass

async def _get_log_channels(bot: commands.Bot, guild_id: int) -> dict:
    from utils import db
    s = await db.get_guild_settings(guild_id)
    return s or {}


class Logger(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Snipe cache (also used by snipe command)
        self._deleted: dict[int, discord.Message] = {}
        self._edited:  dict[int, tuple[str, str]] = {}

    # ══════════════════════════════════════════════════════════
    #  MESSAGE EVENTS
    # ══════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        self._deleted[message.channel.id] = message
        s = await _get_log_channels(self.bot, message.guild.id)
        ch_id = s.get("log_msg_delete") or s.get("log_channel")
        if not ch_id:
            return
        content = message.content or "*[no text content]*"
        embed = _log_embed(
            "🗑️ Message Deleted",
            f"**Author:** {message.author.mention} (`{message.author}`)\n"
            f"**Channel:** {message.channel.mention}\n"
            f"**Content:** {content[:1800]}",
            0xe74c3c,
            thumbnail=message.author.display_avatar.url
        )
        embed.add_field(name="User ID",    value=f"`{message.author.id}`",    inline=True)
        embed.add_field(name="Message ID", value=f"`{message.id}`",           inline=True)
        if message.attachments:
            embed.add_field(
                name=f"Attachments ({len(message.attachments)})",
                value="\n".join(a.filename for a in message.attachments),
                inline=False)
        await _send(message.guild, ch_id, embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild:
            return
        if before.content == after.content:
            return
        self._edited[before.id] = (before.content, after.content)
        s = await _get_log_channels(self.bot, before.guild.id)
        ch_id = s.get("log_msg_edit") or s.get("log_channel")
        if not ch_id:
            return
        embed = _log_embed(
            "✏️ Message Edited",
            f"**Author:** {before.author.mention} (`{before.author}`)\n"
            f"**Channel:** {before.channel.mention}\n"
            f"[Jump to message]({after.jump_url})",
            0xf39c12,
            thumbnail=before.author.display_avatar.url
        )
        embed.add_field(name="Before", value=(before.content or "*empty*")[:1024], inline=False)
        embed.add_field(name="After",  value=(after.content  or "*empty*")[:1024], inline=False)
        await _send(before.guild, ch_id, embed)

    # ══════════════════════════════════════════════════════════
    #  MEMBER EVENTS
    # ══════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        s = await _get_log_channels(self.bot, member.guild.id)
        ch_id = s.get("log_member_join") or s.get("log_channel")
        if not ch_id:
            return
        created_ago = (datetime.now(timezone.utc) - member.created_at).days
        age_warn = " ⚠️ **New account!**" if created_ago < 7 else ""
        embed = _log_embed(
            "📥 Member Joined",
            f"{member.mention} joined the server",
            0x2ecc71,
            fields=[
                ("User",         f"`{member}` (`{member.id}`)", True),
                ("Account Age",  f"`{created_ago}` days{age_warn}", True),
                ("Member Count", f"`{member.guild.member_count}`", True),
                ("Created",      f"<t:{int(member.created_at.timestamp())}:R>", True),
            ],
            thumbnail=member.display_avatar.url
        )
        await _send(member.guild, ch_id, embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        s = await _get_log_channels(self.bot, member.guild.id)
        ch_id = s.get("log_member_leave") or s.get("log_channel")
        if not ch_id:
            return
        joined_ago = ""
        if member.joined_at:
            days = (datetime.now(timezone.utc) - member.joined_at).days
            joined_ago = f"`{days}` days ago"
        roles = [r.mention for r in member.roles if r != member.guild.default_role]
        embed = _log_embed(
            "📤 Member Left",
            f"{member.mention} (`{member}`) left the server",
            0xe74c3c,
            fields=[
                ("User ID",    f"`{member.id}`", True),
                ("Joined",     joined_ago or "Unknown", True),
                ("Roles",      " ".join(roles[:10]) or "None", False),
            ],
            thumbnail=member.display_avatar.url
        )
        await _send(member.guild, ch_id, embed)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        s = await _get_log_channels(self.bot, before.guild.id)
        ch_id = s.get("log_member_update") or s.get("log_channel")
        if not ch_id:
            return

        # Nickname change
        if before.nick != after.nick:
            embed = _log_embed(
                "✏️ Nickname Changed",
                f"{after.mention} (`{after}`)",
                0x3498db,
                fields=[
                    ("Before", before.nick or "*none*", True),
                    ("After",  after.nick  or "*none*", True),
                ],
                thumbnail=after.display_avatar.url
            )
            await _send(before.guild, ch_id, embed)

        # Role changes
        added   = set(after.roles)  - set(before.roles)
        removed = set(before.roles) - set(after.roles)
        if added or removed:
            s2 = await _get_log_channels(self.bot, before.guild.id)
            role_ch = s2.get("log_roles") or ch_id
            fields = []
            if added:
                fields.append(("Roles Added",   " ".join(r.mention for r in added),   False))
            if removed:
                fields.append(("Roles Removed", " ".join(r.mention for r in removed), False))
            embed = _log_embed(
                "🎭 Roles Updated",
                f"{after.mention} (`{after}`)",
                0x9b59b6, fields=fields,
                thumbnail=after.display_avatar.url
            )
            await _send(before.guild, role_ch, embed)

    # ══════════════════════════════════════════════════════════
    #  VOICE EVENTS
    # ══════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member,
                                     before: discord.VoiceState,
                                     after: discord.VoiceState):
        if member.bot:
            return
        s = await _get_log_channels(self.bot, member.guild.id)
        ch_id = s.get("log_voice")
        if not ch_id:
            return

        if before.channel is None and after.channel is not None:
            desc = f"{member.mention} joined **{after.channel.name}**"
            color = 0x2ecc71
            title = "🔊 Joined Voice"
        elif before.channel is not None and after.channel is None:
            desc = f"{member.mention} left **{before.channel.name}**"
            color = 0xe74c3c
            title = "🔇 Left Voice"
        elif before.channel != after.channel:
            desc = f"{member.mention} moved from **{before.channel.name}** → **{after.channel.name}**"
            color = 0xf39c12
            title = "🔀 Moved Voice"
        else:
            return  # mute/deafen state only — skip to keep logs clean

        embed = _log_embed(title, desc, color, thumbnail=member.display_avatar.url)
        await _send(member.guild, ch_id, embed)

    # ══════════════════════════════════════════════════════════
    #  GUILD EVENTS
    # ══════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        s = await _get_log_channels(self.bot, channel.guild.id)
        ch_id = s.get("log_channel")
        if not ch_id:
            return
        embed = _log_embed(
            "📁 Channel Created",
            f"**{channel.name}** (`{channel.type}`)",
            0x2ecc71,
            fields=[("ID", f"`{channel.id}`", True), ("Category", str(channel.category) or "None", True)]
        )
        await _send(channel.guild, ch_id, embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        s = await _get_log_channels(self.bot, channel.guild.id)
        ch_id = s.get("log_channel")
        if not ch_id:
            return
        embed = _log_embed(
            "🗑️ Channel Deleted",
            f"**{channel.name}** (`{channel.type}`)",
            0xe74c3c,
            fields=[("ID", f"`{channel.id}`", True)]
        )
        await _send(channel.guild, ch_id, embed)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        s = await _get_log_channels(self.bot, role.guild.id)
        ch_id = s.get("log_roles") or s.get("log_channel")
        if not ch_id:
            return
        embed = _log_embed(
            "🎭 Role Created",
            f"{role.mention} `{role.name}`",
            0x2ecc71,
            fields=[("ID", f"`{role.id}`", True), ("Color", str(role.color), True)]
        )
        await _send(role.guild, ch_id, embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        s = await _get_log_channels(self.bot, role.guild.id)
        ch_id = s.get("log_roles") or s.get("log_channel")
        if not ch_id:
            return
        embed = _log_embed(
            "🗑️ Role Deleted",
            f"`{role.name}` (ID: `{role.id}`)",
            0xe74c3c
        )
        await _send(role.guild, ch_id, embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Logger(bot))
