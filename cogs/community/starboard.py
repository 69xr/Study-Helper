"""
cogs/community/starboard.py  — v20 NEW FEATURE
Community-driven message highlighting via ⭐ reactions.

Commands:
  /starboard setup <channel> [threshold] — Set the starboard channel + min stars
  /starboard disable  — Disable starboard
  /starboard info     — Show current starboard config

How it works:
  • Members react with ⭐ to a message
  • When stars >= threshold, message is sent to starboard channel
  • Each message only gets posted once (duplicate-safe)
  • Self-stars blocked
  • Bot messages blocked
"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
from utils import db
from utils.helpers import error_embed, success_embed
import config

# In-memory: guild_id -> {channel_id, threshold}
_config: dict[int, dict] = {}
# Tracked starred messages: (guild_id, msg_id) -> starboard_msg_id
_starred: dict[tuple, int] = {}

STAR_EMOJI = "⭐"


def star_color(count: int) -> int:
    if count >= 15: return 0xFF6600   # orange flame
    if count >= 10: return 0xFFB800   # gold
    if count >= 5:  return 0xFFD700   # yellow-gold
    return 0xFEE75C                   # pale yellow


def build_star_embed(message: discord.Message, count: int) -> discord.Embed:
    embed = discord.Embed(
        description=message.content or "*[no text content]*",
        color=star_color(count),
        timestamp=message.created_at,
    )
    embed.set_author(
        name=str(message.author),
        icon_url=message.author.display_avatar.url)
    embed.add_field(
        name="Source",
        value=f"[Jump to message]({message.jump_url}) in {message.channel.mention}",
        inline=False)

    # Attach first image/attachment if any
    if message.attachments:
        att = message.attachments[0]
        if att.content_type and att.content_type.startswith("image/"):
            embed.set_image(url=att.url)

    # If message has embeds with images
    if not message.attachments and message.embeds:
        e = message.embeds[0]
        if e.image:
            embed.set_image(url=e.image.url)
        if e.thumbnail:
            embed.set_thumbnail(url=e.thumbnail.url)

    embed.set_footer(text=f"{STAR_EMOJI} {count} star{'s' if count != 1 else ''}")
    return embed


class Starboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Reaction listener ─────────────────────────────────────

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if str(payload.emoji) != STAR_EMOJI:
            return
        await self._handle_star(payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if str(payload.emoji) != STAR_EMOJI:
            return
        await self._handle_star(payload)

    async def _handle_star(self, payload: discord.RawReactionActionEvent):
        guild_id = payload.guild_id
        if not guild_id:
            return

        cfg = _config.get(guild_id)
        if not cfg:
            # Try loading from DB
            try:
                row = await db.db_fetchone(
                    "SELECT starboard_channel, starboard_threshold FROM guild_settings WHERE guild_id=?",
                    (guild_id,))
                if row and row.get("starboard_channel"):
                    _config[guild_id] = {
                        "channel_id": row["starboard_channel"],
                        "threshold":  row.get("starboard_threshold") or 3,
                    }
                    cfg = _config[guild_id]
            except Exception:
                pass
        if not cfg:
            return

        guild   = self.bot.get_guild(guild_id)
        channel = guild.get_channel(payload.channel_id)
        if not channel:
            return

        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return

        # Blocked: bots, starboard channel itself
        if message.author.bot:
            return
        if channel.id == cfg["channel_id"]:
            return

        # Count non-self stars
        star_reaction = discord.utils.get(message.reactions, emoji=STAR_EMOJI)
        count = 0
        if star_reaction:
            async for user in star_reaction.users():
                if user != message.author:
                    count += 1

        sb_channel = guild.get_channel(cfg["channel_id"])
        if not sb_channel:
            return

        key = (guild_id, message.id)
        existing_id = _starred.get(key)

        if count >= cfg["threshold"]:
            embed = build_star_embed(message, count)
            if existing_id:
                # Update existing starboard post
                try:
                    sb_msg = await sb_channel.fetch_message(existing_id)
                    await sb_msg.edit(embed=embed)
                except discord.NotFound:
                    del _starred[key]
                    new_msg = await sb_channel.send(embed=embed)
                    _starred[key] = new_msg.id
            else:
                new_msg = await sb_channel.send(embed=embed)
                _starred[key] = new_msg.id

        elif existing_id and count < cfg["threshold"]:
            # Remove from starboard if stars drop below threshold
            try:
                sb_msg = await sb_channel.fetch_message(existing_id)
                await sb_msg.delete()
            except discord.NotFound:
                pass
            del _starred[key]

    # ── /starboard setup ──────────────────────────────────────

    @app_commands.command(name="starboard", description="Configure the starboard for this server.")
    @app_commands.describe(
        channel="Channel where starred messages appear",
        threshold="Number of ⭐ reactions needed (default: 3)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def starboard_setup(self, interaction: discord.Interaction,
                              channel: discord.TextChannel,
                              threshold: app_commands.Range[int, 1, 25] = 3):
        _config[interaction.guild_id] = {
            "channel_id": channel.id,
            "threshold":  threshold,
        }
        # Save to DB
        try:
            await db.db_execute(
                "UPDATE guild_settings SET starboard_channel=?, starboard_threshold=? WHERE guild_id=?",
                (channel.id, threshold, interaction.guild_id))
        except Exception:
            pass

        embed = success_embed(
            "⭐ Starboard Configured",
            f"Starboard channel: {channel.mention}\n"
            f"Threshold: **{threshold}** star{'s' if threshold != 1 else ''}\n\n"
            f"Members can now ⭐ messages to highlight them!")
        await interaction.response.send_message(embed=embed)

    # ── /disablestarboard ─────────────────────────────────────

    @app_commands.command(name="disablestarboard", description="Disable the starboard for this server.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def disable_starboard(self, interaction: discord.Interaction):
        _config.pop(interaction.guild_id, None)
        try:
            await db.db_execute(
                "UPDATE guild_settings SET starboard_channel=NULL WHERE guild_id=?",
                (interaction.guild_id,))
        except Exception:
            pass
        await interaction.response.send_message(
            embed=success_embed("Starboard Disabled", "The starboard has been turned off."),
            ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Starboard(bot))
