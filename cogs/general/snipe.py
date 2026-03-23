"""
cogs/general/snipe.py  — v20
Improvements:
  • /editsnipe — show the before/after of the last edited message
  • Stores last 3 deleted messages per channel (cycle with /snipe <index>)
  • Proper timestamp display using Discord <t:> format
  • Moderator-only /clearsnipe to wipe cache for a channel
"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
from collections import deque

# Channel caches — store last 3 deleted/edited per channel
_snipe_cache: dict[int, deque] = {}
_edit_cache:  dict[int, dict]  = {}

MAX_SNIPE = 3


class Snipe(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── Events ────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        ch = message.channel.id
        if ch not in _snipe_cache:
            _snipe_cache[ch] = deque(maxlen=MAX_SNIPE)
        attachment_url = message.attachments[0].url if message.attachments else None
        _snipe_cache[ch].appendleft({
            "content":       message.content or "*[no text content]*",
            "author_name":   str(message.author),
            "author_avatar": message.author.display_avatar.url,
            "author_id":     message.author.id,
            "deleted_at":    datetime.now(timezone.utc),
            "attachment":    attachment_url,
        })

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild:
            return
        if before.content == after.content:
            return
        _edit_cache[before.channel.id] = {
            "before":        before.content or "*[no text]*",
            "after":         after.content  or "*[no text]*",
            "author_name":   str(before.author),
            "author_avatar": before.author.display_avatar.url,
            "author_id":     before.author.id,
            "edited_at":     datetime.now(timezone.utc),
            "jump_url":      after.jump_url,
        }

    # ── /snipe ────────────────────────────────────────────────

    @app_commands.command(name="snipe", description="Show recently deleted messages in this channel.")
    @app_commands.describe(index="Which deleted message to show (1 = most recent, max 3)")
    async def snipe(self, interaction: discord.Interaction,
                    index: app_commands.Range[int, 1, 3] = 1):
        cache = _snipe_cache.get(interaction.channel_id)
        if not cache or len(cache) < index:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="📭 Nothing to snipe here — no recently deleted messages.",
                    color=0xED4245),
                ephemeral=True)
            return

        data = list(cache)[index - 1]
        ts   = int(data["deleted_at"].timestamp())
        total = len(cache)

        embed = discord.Embed(description=data["content"], color=0xFEE75C,
                               timestamp=data["deleted_at"])
        embed.set_author(name=data["author_name"], icon_url=data["author_avatar"])
        embed.set_footer(text=f"Deleted <t:{ts}:R> • Snipe {index}/{total}")
        if data["attachment"]:
            embed.set_image(url=data["attachment"])

        await interaction.response.send_message(embed=embed)

    # ── /editsnipe ────────────────────────────────────────────

    @app_commands.command(name="editsnipe", description="Show the last edited message in this channel.")
    async def editsnipe(self, interaction: discord.Interaction):
        data = _edit_cache.get(interaction.channel_id)
        if not data:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="📭 No recently edited messages found.",
                    color=0xED4245),
                ephemeral=True)
            return

        ts = int(data["edited_at"].timestamp())
        embed = discord.Embed(title="✏️ Message Edit Snipe", color=0x5865F2,
                               timestamp=data["edited_at"])
        embed.set_author(name=data["author_name"], icon_url=data["author_avatar"])
        embed.add_field(name="Before", value=data["before"][:1020], inline=False)
        embed.add_field(name="After",  value=data["after"][:1020],  inline=False)
        embed.set_footer(text=f"Edited <t:{ts}:R>")

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Jump to Message", url=data["jump_url"], style=discord.ButtonStyle.link))
        await interaction.response.send_message(embed=embed, view=view)

    # ── /clearsnipe ───────────────────────────────────────────

    @app_commands.command(name="clearsnipe", description="Clear the snipe cache for this channel. (Mod only)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clearsnipe(self, interaction: discord.Interaction):
        cleared = False
        if interaction.channel_id in _snipe_cache:
            del _snipe_cache[interaction.channel_id]
            cleared = True
        if interaction.channel_id in _edit_cache:
            del _edit_cache[interaction.channel_id]
            cleared = True
        if cleared:
            await interaction.response.send_message(
                embed=discord.Embed(description="🗑️ Snipe cache cleared for this channel.", color=0x57F287),
                ephemeral=True)
        else:
            await interaction.response.send_message(
                embed=discord.Embed(description="Nothing to clear.", color=0xED4245),
                ephemeral=True)


async def setup(bot):
    await bot.add_cog(Snipe(bot))
