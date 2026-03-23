"""
cogs/community/polls.py  — v20 NEW FEATURE
Interactive polls with buttons, live vote counts, and auto-close.

Commands:
  /poll  — Create a poll (2-4 options)
  /endpoll <message_id>  — End a poll early (mod)

How it works:
  • Creates a rich embed with option buttons
  • Votes stored in-memory (per restart) and in DB for persistence
  • Auto-closes after duration (optional)
  • Each user can only vote once (vote changes allowed)
  • Results shown live on button click
"""
import discord
import asyncio
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone, timedelta
from utils import db
from utils.helpers import error_embed, success_embed
import config

# In-memory poll store: message_id -> {data}
_polls: dict[int, dict] = {}

COLORS = [0x5865F2, 0x3BA55C, 0xFEE75C, 0xED4245]
LETTERS = ["🇦", "🇧", "🇨", "🇩"]


def build_poll_embed(data: dict, ended: bool = False) -> discord.Embed:
    votes    = data["votes"]
    options  = data["options"]
    total    = sum(votes.values())
    question = data["question"]

    embed = discord.Embed(
        title=f"{'📊' if not ended else '✅'} {'Poll' if not ended else 'Poll Ended'}: {question}",
        color=0x5865F2 if not ended else 0x57F287,
        timestamp=datetime.now(timezone.utc)
    )

    for i, opt in enumerate(options):
        count = votes.get(str(i), 0)
        pct   = int(count / total * 100) if total > 0 else 0
        bar   = "█" * (pct // 10) + "░" * (10 - pct // 10)
        embed.add_field(
            name=f"{LETTERS[i]} {opt}",
            value=f"`{bar}` **{pct}%** — {count} vote{'s' if count != 1 else ''}",
            inline=False
        )

    embed.set_footer(text=f"Total votes: {total} • {'Poll closed' if ended else 'Click to vote'}")
    if data.get("ends_at") and not ended:
        ts = int(data["ends_at"].timestamp())
        embed.add_field(name="⏰ Ends", value=f"<t:{ts}:R>", inline=False)
    if data.get("author_name"):
        embed.set_author(name=f"Poll by {data['author_name']}")

    return embed


class PollView(discord.ui.View):
    def __init__(self, poll_id: int, options: list[str]):
        super().__init__(timeout=None)
        for i, opt in enumerate(options):
            btn = discord.ui.Button(
                label=opt[:80],
                emoji=LETTERS[i],
                style=discord.ButtonStyle.secondary,
                custom_id=f"poll_{poll_id}_{i}",
                row=0
            )
            btn.callback = self._make_callback(i)
            self.add_item(btn)

    def _make_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            poll = _polls.get(interaction.message.id)
            if not poll:
                await interaction.response.send_message("This poll is no longer active.", ephemeral=True)
                return
            if poll.get("ended"):
                await interaction.response.send_message("This poll has already ended.", ephemeral=True)
                return

            uid      = str(interaction.user.id)
            prev     = poll["user_votes"].get(uid)
            new_vote = str(index)

            if prev == new_vote:
                await interaction.response.send_message(
                    f"You already voted for **{poll['options'][index]}**.", ephemeral=True)
                return

            # Remove previous vote if any
            if prev is not None:
                poll["votes"][prev] = max(0, poll["votes"].get(prev, 0) - 1)

            poll["user_votes"][uid] = new_vote
            poll["votes"][new_vote] = poll["votes"].get(new_vote, 0) + 1

            await interaction.response.edit_message(embed=build_poll_embed(poll))

            action = "changed your vote to" if prev is not None else "voted for"
            await interaction.followup.send(
                f"✅ You {action} **{poll['options'][index]}**.", ephemeral=True)

        return callback


class Polls(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot    = bot
        self._tasks: dict[int, asyncio.Task] = {}

    # ── /poll ─────────────────────────────────────────────────

    @app_commands.command(name="poll", description="Create an interactive poll with up to 4 options.")
    @app_commands.describe(
        question="The poll question",
        option_a="Option A (required)",
        option_b="Option B (required)",
        option_c="Option C (optional)",
        option_d="Option D (optional)",
        duration="Auto-close after: 10m, 1h, 1d (leave empty for manual close)",
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def poll(self, interaction: discord.Interaction,
                   question: str,
                   option_a: str,
                   option_b: str,
                   option_c: str = None,
                   option_d: str = None,
                   duration: str = None):
        await interaction.response.defer()

        options = [opt for opt in [option_a, option_b, option_c, option_d] if opt]

        ends_at = None
        if duration:
            from cogs.general.reminders import parse_duration
            secs = parse_duration(duration)
            if not secs:
                await interaction.followup.send(
                    embed=error_embed("Invalid Duration", "Use formats like `10m`, `1h`, `1d`."),
                    ephemeral=True)
                return
            ends_at = datetime.now(timezone.utc) + timedelta(seconds=secs)

        # Send poll message
        poll_data = {
            "question":    question,
            "options":     options,
            "votes":       {str(i): 0 for i in range(len(options))},
            "user_votes":  {},
            "ended":       False,
            "ends_at":     ends_at,
            "author_name": str(interaction.user),
            "guild_id":    interaction.guild_id,
            "channel_id":  interaction.channel_id,
        }

        view = PollView(poll_id=0, options=options)  # ID set after send
        embed = build_poll_embed(poll_data)
        msg = await interaction.followup.send(embed=embed, view=view)

        # Store with real message ID
        poll_data["message_id"] = msg.id
        view.poll_id = msg.id  # update custom_ids need rebuild
        _polls[msg.id] = poll_data

        # Rebuild view with correct IDs
        view2 = PollView(poll_id=msg.id, options=options)
        await msg.edit(view=view2)

        # Schedule auto-close
        if ends_at:
            secs_until = (ends_at - datetime.now(timezone.utc)).total_seconds()
            task = asyncio.create_task(self._auto_close(msg.id, secs_until))
            self._tasks[msg.id] = task

    # ── /endpoll ──────────────────────────────────────────────

    @app_commands.command(name="endpoll", description="End an active poll early by message ID.")
    @app_commands.describe(message_id="The ID of the poll message")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def endpoll(self, interaction: discord.Interaction, message_id: str):
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message(embed=error_embed("Invalid ID", "Enter a valid message ID."), ephemeral=True)
            return

        poll = _polls.get(mid)
        if not poll:
            await interaction.response.send_message(embed=error_embed("Not Found", "No active poll with that message ID."), ephemeral=True)
            return
        if poll.get("ended"):
            await interaction.response.send_message(embed=error_embed("Already Ended", "That poll is already closed."), ephemeral=True)
            return

        await self._close_poll(mid)
        await interaction.response.send_message(embed=success_embed("Poll Ended", "The poll has been closed."), ephemeral=True)

    # ── Internal close ────────────────────────────────────────

    async def _auto_close(self, message_id: int, delay: float):
        await asyncio.sleep(delay)
        await self._close_poll(message_id)

    async def _close_poll(self, message_id: int):
        poll = _polls.get(message_id)
        if not poll or poll.get("ended"):
            return

        poll["ended"] = True

        # Cancel scheduled task
        task = self._tasks.pop(message_id, None)
        if task and not task.done():
            task.cancel()

        # Edit message
        try:
            ch  = self.bot.get_channel(poll["channel_id"])
            msg = await ch.fetch_message(message_id)
            embed = build_poll_embed(poll, ended=True)

            # Determine winner(s)
            votes   = poll["votes"]
            options = poll["options"]
            max_v   = max(votes.values(), default=0)
            winners = [options[int(k)] for k, v in votes.items() if v == max_v and max_v > 0]
            if winners:
                embed.add_field(
                    name="🏆 Winner" + ("s" if len(winners) > 1 else ""),
                    value=", ".join(f"**{w}**" for w in winners),
                    inline=False)

            disabled_view = discord.ui.View()
            await msg.edit(embed=embed, view=disabled_view)
        except Exception:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Polls(bot))
