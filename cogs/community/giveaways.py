"""
cogs/community/giveaways.py  — v20 NEW FEATURE
Full giveaway system with button entry, auto-draw, and reroll.

Commands:
  /giveaway start  — Start a giveaway
  /giveaway end    — End a giveaway early
  /giveaway reroll — Reroll winners for a completed giveaway
  /giveaway list   — List active giveaways in this server
"""
import discord
import asyncio
import random
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone, timedelta
from utils.helpers import error_embed, success_embed
import re

# In-memory store: message_id -> giveaway data
_giveaways: dict[int, dict] = {}


def parse_duration(s: str) -> int | None:
    total = 0
    for num, unit in re.findall(r"(\d+)\s*([smhd])", s.lower()):
        n = int(num)
        if unit == "s": total += n
        elif unit == "m": total += n * 60
        elif unit == "h": total += n * 3600
        elif unit == "d": total += n * 86400
    return total if total > 0 else None


def giveaway_embed(data: dict, ended: bool = False) -> discord.Embed:
    entries  = data["entries"]
    prize    = data["prize"]
    winners  = data["winners_count"]
    ends_at  = data["ends_at"]
    host     = data["host_name"]
    host_id  = data["host_id"]

    color = 0xFFD700 if not ended else 0x57F287
    title = f"{'🎉' if not ended else '🏆'} {'GIVEAWAY' if not ended else 'GIVEAWAY ENDED'}"

    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="Prize",   value=f"**{prize}**",             inline=True)
    embed.add_field(name="Winners", value=f"`{winners}`",             inline=True)
    embed.add_field(name="Entries", value=f"`{len(entries)}`",        inline=True)
    embed.add_field(name="Hosted by", value=f"<@{host_id}>",         inline=True)

    if data.get("req_role"):
        embed.add_field(name="Requirement", value=f"<@&{data['req_role']}>", inline=True)

    if not ended:
        ts = int(ends_at.timestamp())
        embed.add_field(name="Ends", value=f"<t:{ts}:R>", inline=True)
        embed.set_footer(text="🎟️ Click the button below to enter!")
    else:
        drawn = data.get("drawn_winners", [])
        if drawn:
            embed.add_field(
                name="🏆 Winners",
                value=" ".join(f"<@{uid}>" for uid in drawn),
                inline=False)
        embed.set_footer(text="Giveaway ended")

    return embed


class GiveawayView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Enter Giveaway", emoji="🎉", style=discord.ButtonStyle.success, custom_id="giveaway_enter")
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        gw = _giveaways.get(interaction.message.id)
        if not gw:
            await interaction.response.send_message("This giveaway is no longer active.", ephemeral=True)
            return
        if gw.get("ended"):
            await interaction.response.send_message("This giveaway has already ended.", ephemeral=True)
            return

        uid = interaction.user.id

        # Check role requirement
        if gw.get("req_role"):
            role = interaction.guild.get_role(gw["req_role"])
            if role and role not in interaction.user.roles:
                await interaction.response.send_message(
                    f"❌ You need the **{role.name}** role to enter this giveaway.", ephemeral=True)
                return

        if uid in gw["entries"]:
            # Allow leaving
            gw["entries"].remove(uid)
            await interaction.response.edit_message(embed=giveaway_embed(gw))
            await interaction.followup.send("🚪 You have left the giveaway.", ephemeral=True)
        else:
            gw["entries"].append(uid)
            await interaction.response.edit_message(embed=giveaway_embed(gw))
            await interaction.followup.send("🎉 You've entered the giveaway! Good luck!", ephemeral=True)


# ── Cog ────────────────────────────────────────────────────────

gw_group = app_commands.Group(name="giveaway", description="Giveaway management.")


class Giveaways(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot    = bot
        self._tasks: dict[int, asyncio.Task] = {}

    @app_commands.command(name="giveaway", description="Giveaway system — use /giveaway start | end | reroll | list")
    async def giveaway_placeholder(self, interaction: discord.Interaction):
        await interaction.response.send_message("Use `/giveaway start`, `/giveaway end`, `/giveaway reroll`, or `/giveaway list`.", ephemeral=True)

    # ── /giveaway start ───────────────────────────────────────

    @app_commands.command(name="gstart", description="Start a giveaway in this channel.")
    @app_commands.describe(
        prize="What are you giving away?",
        duration="Duration: 10m, 2h, 1d",
        winners="Number of winners (1–10)",
        channel="Channel for the giveaway (default: current)",
        req_role="Role required to enter (optional)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def gstart(self, interaction: discord.Interaction,
                     prize: str,
                     duration: str,
                     winners: app_commands.Range[int, 1, 10] = 1,
                     channel: discord.TextChannel = None,
                     req_role: discord.Role = None):
        await interaction.response.defer(ephemeral=True)

        secs = parse_duration(duration)
        if not secs or secs < 10:
            await interaction.followup.send(
                embed=error_embed("Invalid Duration", "Use `10m`, `2h`, `1d`. Minimum 10 seconds."),
                ephemeral=True)
            return
        if secs > 30 * 86400:
            await interaction.followup.send(embed=error_embed("Too Long", "Max giveaway duration is 30 days."), ephemeral=True)
            return

        target_ch = channel or interaction.channel
        ends_at   = datetime.now(timezone.utc) + timedelta(seconds=secs)

        gw_data = {
            "prize":          prize,
            "winners_count":  winners,
            "entries":        [],
            "ended":          False,
            "ends_at":        ends_at,
            "host_id":        interaction.user.id,
            "host_name":      str(interaction.user),
            "guild_id":       interaction.guild_id,
            "channel_id":     target_ch.id,
            "req_role":       req_role.id if req_role else None,
            "drawn_winners":  [],
        }

        view = GiveawayView()
        embed = giveaway_embed(gw_data)
        msg = await target_ch.send(embed=embed, view=view)

        gw_data["message_id"] = msg.id
        _giveaways[msg.id] = gw_data

        task = asyncio.create_task(self._auto_end(msg.id, secs))
        self._tasks[msg.id] = task

        await interaction.followup.send(
            embed=success_embed("Giveaway Started!", f"[Jump to giveaway]({msg.jump_url})"),
            ephemeral=True)

    # ── /gend ─────────────────────────────────────────────────

    @app_commands.command(name="gend", description="End a giveaway early by its message ID.")
    @app_commands.describe(message_id="Message ID of the giveaway")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def gend(self, interaction: discord.Interaction, message_id: str):
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message(embed=error_embed("Invalid ID"), ephemeral=True)
            return
        gw = _giveaways.get(mid)
        if not gw or gw.get("ended"):
            await interaction.response.send_message(embed=error_embed("Not Found", "No active giveaway with that ID."), ephemeral=True)
            return
        await self._draw_winners(mid)
        await interaction.response.send_message(embed=success_embed("Giveaway Ended", "Winners have been drawn."), ephemeral=True)

    # ── /greroll ──────────────────────────────────────────────

    @app_commands.command(name="greroll", description="Reroll winners for a completed giveaway.")
    @app_commands.describe(message_id="Message ID of the ended giveaway")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def greroll(self, interaction: discord.Interaction, message_id: str):
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message(embed=error_embed("Invalid ID"), ephemeral=True)
            return
        gw = _giveaways.get(mid)
        if not gw:
            await interaction.response.send_message(embed=error_embed("Not Found", "No giveaway record found with that ID."), ephemeral=True)
            return
        if not gw.get("ended"):
            await interaction.response.send_message(embed=error_embed("Not Ended", "End the giveaway first with `/gend`."), ephemeral=True)
            return
        if len(gw["entries"]) == 0:
            await interaction.response.send_message(embed=error_embed("No Entries", "No one entered this giveaway."), ephemeral=True)
            return

        count    = min(gw["winners_count"], len(gw["entries"]))
        new_wins = random.sample(gw["entries"], count)
        gw["drawn_winners"] = new_wins

        win_mentions = " ".join(f"<@{uid}>" for uid in new_wins)
        try:
            ch  = self.bot.get_channel(gw["channel_id"])
            msg = await ch.fetch_message(mid)
            await msg.edit(embed=giveaway_embed(gw, ended=True))
            await ch.send(f"🎉 New winner{'s' if count > 1 else ''} for **{gw['prize']}**: {win_mentions} — Congratulations!")
        except Exception:
            pass

        await interaction.response.send_message(
            embed=success_embed("Rerolled!", f"New winner(s): {win_mentions}"),
            ephemeral=True)

    # ── /glist ────────────────────────────────────────────────

    @app_commands.command(name="glist", description="List all active giveaways in this server.")
    async def glist(self, interaction: discord.Interaction):
        active = [gw for gw in _giveaways.values()
                  if gw["guild_id"] == interaction.guild_id and not gw.get("ended")]
        if not active:
            await interaction.response.send_message(
                embed=discord.Embed(description="No active giveaways in this server.", color=0x5865F2),
                ephemeral=True)
            return

        embed = discord.Embed(title="🎉 Active Giveaways", color=0xFFD700)
        for gw in active[:10]:
            ts = int(gw["ends_at"].timestamp())
            embed.add_field(
                name=gw["prize"],
                value=f"Entries: `{len(gw['entries'])}` • Ends <t:{ts}:R> • [Jump](https://discord.com/channels/{gw['guild_id']}/{gw['channel_id']}/{gw['message_id']})",
                inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── Internal ──────────────────────────────────────────────

    async def _auto_end(self, message_id: int, delay: float):
        await asyncio.sleep(delay)
        await self._draw_winners(message_id)

    async def _draw_winners(self, message_id: int):
        gw = _giveaways.get(message_id)
        if not gw or gw.get("ended"):
            return
        gw["ended"] = True

        task = self._tasks.pop(message_id, None)
        if task and not task.done():
            task.cancel()

        entries = gw["entries"]
        count   = min(gw["winners_count"], len(entries))

        if count > 0:
            winners = random.sample(entries, count)
        else:
            winners = []

        gw["drawn_winners"] = winners

        try:
            ch  = self.bot.get_channel(gw["channel_id"])
            msg = await ch.fetch_message(message_id)
            embed = giveaway_embed(gw, ended=True)
            await msg.edit(embed=embed, view=discord.ui.View())  # remove buttons

            if winners:
                win_mentions = " ".join(f"<@{uid}>" for uid in winners)
                await ch.send(
                    f"🎉 Congratulations {win_mentions}! You won **{gw['prize']}**!\n"
                    f"> Use `/greroll {message_id}` to reroll winners.")
            else:
                await ch.send(f"😔 No one entered the giveaway for **{gw['prize']}**.")
        except Exception:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Giveaways(bot))
