"""
cogs/general/afk.py  —  AFK system
Commands:  /afk [reason]
Listeners: on_message — auto-return, mention detection
"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
from utils import db
from utils.helpers import success_embed, info_embed
import config


# ── Helpers ──────────────────────────────────────────────────────

def _format_duration(seconds: float) -> str:
    """Human-readable duration from seconds."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s}s" if s else f"{m}m"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h {m}m" if m else f"{h}h"
    d, h = divmod(h, 24)
    return f"{d}d {h}h" if h else f"{d}d"


def _afk_nick(display_name: str) -> str:
    """Build '[AFK] Name' capped at 32 chars (Discord limit)."""
    prefix = "[AFK] "
    max_name = 32 - len(prefix)
    return f"{prefix}{display_name[:max_name]}"


# ── Cog ──────────────────────────────────────────────────────────

class AFK(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # In-memory set to ignore the bot's own nick-change messages
        self._returning: set[int] = set()   # user_ids currently being un-AFK'd

    # ─── /afk ───────────────────────────────────────────────────
    @app_commands.command(name="afk", description="Set your AFK status. People who ping you will be notified.")
    @app_commands.describe(reason="Why are you going AFK? (optional)")
    async def afk_cmd(
        self,
        interaction: discord.Interaction,
        reason: str = "AFK"
    ):
        guild_id = interaction.guild_id
        user     = interaction.user

        # Already AFK?
        existing = await db.get_afk(guild_id, user.id)
        if existing:
            await interaction.response.send_message(
                embed=self._already_afk_embed(existing),
                ephemeral=True
            )
            return

        # Save original nick before we touch it
        original_nick: str | None = user.nick if hasattr(user, "nick") else None

        # Try to rename to [AFK] username
        new_nick = _afk_nick(user.display_name)
        nick_changed = False
        try:
            if isinstance(user, discord.Member):
                await user.edit(nick=new_nick, reason="AFK system")
                nick_changed = True
        except (discord.Forbidden, discord.HTTPException):
            pass   # Bot lacks perm to rename — that's fine

        # Persist to DB
        await db.set_afk(guild_id, user.id, reason[:500], original_nick)

        # Respond
        embed = discord.Embed(
            title="💤  You're now AFK",
            description=f"**Reason:** {reason}\n\nI'll notify anyone who pings you.",
            color=config.Colors.INFO
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        if not nick_changed:
            embed.set_footer(text="Note: I couldn't rename you — missing permissions.")
        else:
            embed.set_footer(text=f"Severus • Nickname → {new_nick}")

        await interaction.response.send_message(embed=embed)

    # ─── on_message ─────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore DMs, bots, system messages
        if not message.guild or message.author.bot or not message.content:
            return

        guild_id  = message.guild.id
        author_id = message.author.id

        # ── 1. Return the author from AFK if they're AFK ────────
        if author_id not in self._returning:
            record = await db.get_afk(guild_id, author_id)
            if record:
                # Don't trigger on the /afk command itself
                if message.content.strip().startswith("/afk"):
                    return
                await self._return_from_afk(message, record)
                return  # Don't also process mentions in their own return message

        # ── 2. Check if any mentioned user is AFK ───────────────
        if not message.mentions:
            return

        notified: set[int] = set()
        for mentioned in message.mentions:
            if mentioned.bot or mentioned.id in notified:
                continue
            afk_record = await db.get_afk(guild_id, mentioned.id)
            if afk_record:
                notified.add(mentioned.id)
                embed = self._mention_embed(mentioned, afk_record)
                try:
                    await message.reply(embed=embed, mention_author=False)
                except (discord.Forbidden, discord.HTTPException):
                    pass

    # ── Internal helpers ─────────────────────────────────────────

    async def _return_from_afk(
        self,
        message: discord.Message,
        record: dict
    ) -> None:
        """Remove AFK, restore nickname, notify user."""
        user     = message.author
        guild_id = message.guild.id

        self._returning.add(user.id)
        try:
            # Remove from DB
            await db.remove_afk(guild_id, user.id)

            # Restore original nickname
            original_nick = record.get("original_nick")
            try:
                if isinstance(user, discord.Member):
                    await user.edit(nick=original_nick, reason="AFK return")
            except (discord.Forbidden, discord.HTTPException):
                pass

            # Calculate duration
            afk_since_str = record.get("afk_since", "")
            duration_str  = "unknown"
            try:
                afk_dt = datetime.fromisoformat(afk_since_str).replace(tzinfo=timezone.utc)
                delta  = (datetime.now(timezone.utc) - afk_dt).total_seconds()
                duration_str = _format_duration(delta)
            except Exception:
                pass

            embed = discord.Embed(
                title="👋  Welcome back!",
                description=(
                    f"Your AFK has been removed.\n\n"
                    f"**Reason you set:** {record.get('reason', 'AFK')}\n"
                    f"**You were away for:** `{duration_str}`"
                ),
                color=config.Colors.SUCCESS
            )
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.set_footer(text="Severus AFK System")

            try:
                await message.reply(embed=embed, mention_author=False, delete_after=8)
            except (discord.Forbidden, discord.HTTPException):
                pass

        finally:
            self._returning.discard(user.id)

    def _mention_embed(self, user: discord.Member, record: dict) -> discord.Embed:
        """Embed shown when someone pings an AFK user."""
        afk_since_str = record.get("afk_since", "")
        duration_str  = "unknown"
        try:
            afk_dt = datetime.fromisoformat(afk_since_str).replace(tzinfo=timezone.utc)
            delta  = (datetime.now(timezone.utc) - afk_dt).total_seconds()
            duration_str = _format_duration(delta)
        except Exception:
            pass

        embed = discord.Embed(
            title="💤  This user is AFK",
            color=config.Colors.WARN
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="👤 User",       value=user.mention,                        inline=True)
        embed.add_field(name="⏱ Away For",   value=f"`{duration_str}`",                 inline=True)
        embed.add_field(name="📋 Reason",     value=record.get("reason", "AFK"),         inline=False)
        embed.set_footer(text="Severus AFK System • They'll be notified when they return")
        return embed

    def _already_afk_embed(self, record: dict) -> discord.Embed:
        afk_since_str = record.get("afk_since", "")
        duration_str  = "unknown"
        try:
            afk_dt = datetime.fromisoformat(afk_since_str).replace(tzinfo=timezone.utc)
            delta  = (datetime.now(timezone.utc) - afk_dt).total_seconds()
            duration_str = _format_duration(delta)
        except Exception:
            pass

        embed = discord.Embed(
            title="💤  You're already AFK",
            description=(
                f"**Reason:** {record.get('reason', 'AFK')}\n"
                f"**Away for:** `{duration_str}`\n\n"
                "Just send any message to remove your AFK."
            ),
            color=config.Colors.INFO
        )
        embed.set_footer(text="Severus AFK System")
        return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(AFK(bot))
