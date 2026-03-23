"""
cogs/general/reminders.py
/remind  /reminders  /remindcancel
Background loop fires every 30 seconds and DMs due reminders.
Survives restarts — all reminders persist in SQLite.
"""
import discord, re, asyncio
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta
from utils import db
from utils.helpers import success_embed, error_embed, base_embed
import config


def parse_duration(s: str) -> int | None:
    """Parse '10m', '2h30m', '1d' → seconds. Returns None on failure."""
    total = 0
    for num, unit in re.findall(r"(\d+)\s*([smhd])", s.lower()):
        n = int(num)
        if unit == "s": total += n
        elif unit == "m": total += n * 60
        elif unit == "h": total += n * 3600
        elif unit == "d": total += n * 86400
    return total if total > 0 else None


def fmt_duration(secs: int) -> str:
    parts = []
    if secs >= 86400: parts.append(f"{secs // 86400}d")
    if (secs % 86400) >= 3600: parts.append(f"{(secs % 86400) // 3600}h")
    if (secs % 3600) >= 60: parts.append(f"{(secs % 3600) // 60}m")
    if secs % 60 and not parts: parts.append(f"{secs % 60}s")
    return " ".join(parts) or "0s"


class Reminders(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_reminders.start()

    def cog_unload(self):
        self.check_reminders.cancel()

    @tasks.loop(seconds=30)
    async def check_reminders(self):
        """Fire any reminders that are due."""
        try:
            due = await db.get_pending_reminders()
        except Exception:
            return

        for r in due:
            await db.mark_reminder_done(r["id"])
            try:
                user = self.bot.get_user(r["user_id"]) or await self.bot.fetch_user(r["user_id"])
                if not user:
                    continue

                embed = discord.Embed(
                    title="⏰ Reminder",
                    description=r["content"],
                    color=config.Colors.INFO,
                    timestamp=datetime.now(timezone.utc),
                )
                embed.set_footer(text=f"Set at {r['created_at'][:16]} UTC • {config.FOOTER_TEXT}")

                # Try the original channel first, fall back to DM
                sent = False
                if r.get("channel_id"):
                    ch = self.bot.get_channel(r["channel_id"])
                    if ch:
                        try:
                            await ch.send(content=user.mention, embed=embed)
                            sent = True
                        except (discord.Forbidden, discord.HTTPException):
                            pass

                if not sent:
                    try:
                        await user.send(embed=embed)
                    except discord.Forbidden:
                        pass  # DMs closed — nothing we can do

            except Exception:
                pass

    @check_reminders.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # ── /remind ──────────────────────────────────────────────

    @app_commands.command(name="remind", description="Set a reminder. I'll ping you when time's up.")
    @app_commands.describe(
        duration="When to remind you: 10m, 2h, 1d, 30s (combine: 1h30m)",
        reminder="What to remind you about"
    )
    async def remind(self, interaction: discord.Interaction, duration: str, reminder: str):
        secs = parse_duration(duration)
        if not secs:
            await interaction.response.send_message(
                embed=error_embed("Invalid Duration",
                    "Use formats like `10m`, `2h`, `1d`, `30s` or combine them: `1h30m`.\n"
                    "Max: 30 days."),
                ephemeral=True)
            return

        if secs > 30 * 86400:
            await interaction.response.send_message(
                embed=error_embed("Too Long", "Maximum reminder duration is **30 days**."),
                ephemeral=True)
            return

        if len(reminder) > 500:
            await interaction.response.send_message(
                embed=error_embed("Too Long", "Reminder text must be under 500 characters."),
                ephemeral=True)
            return

        # Check reminder limit per user
        existing = await db.get_user_reminders(interaction.user.id)
        if len(existing) >= 10:
            await interaction.response.send_message(
                embed=error_embed("Limit Reached",
                    "You already have **10 active reminders**. Cancel one first with `/remindcancel`."),
                ephemeral=True)
            return

        remind_at = (datetime.now(timezone.utc) + timedelta(seconds=secs)).strftime("%Y-%m-%d %H:%M:%S")
        guild_id  = interaction.guild_id
        rid = await db.create_reminder(
            user_id    = interaction.user.id,
            channel_id = interaction.channel_id,
            guild_id   = guild_id,
            content    = reminder,
            remind_at  = remind_at,
        )

        embed = success_embed("⏰ Reminder Set",
            f"I'll remind you in **{fmt_duration(secs)}**.\n\n"
            f"**Reminder:** {reminder}")
        embed.add_field(name="Fires at", value=f"<t:{int((datetime.now(timezone.utc) + timedelta(seconds=secs)).timestamp())}:F>", inline=True)
        embed.add_field(name="ID", value=f"`#{rid}`", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /reminders ───────────────────────────────────────────

    @app_commands.command(name="reminders", description="View all your active reminders.")
    async def reminders_list(self, interaction: discord.Interaction):
        items = await db.get_user_reminders(interaction.user.id)
        if not items:
            await interaction.response.send_message(
                embed=base_embed("⏰ Your Reminders", "You have no active reminders.\nUse `/remind` to set one."),
                ephemeral=True)
            return

        embed = base_embed(f"⏰ Your Reminders ({len(items)})")
        for r in items[:10]:
            try:
                ts = int(datetime.fromisoformat(r["remind_at"].replace(" ", "T")).replace(tzinfo=timezone.utc).timestamp())
                time_str = f"<t:{ts}:R>"
            except Exception:
                time_str = r["remind_at"]
            embed.add_field(
                name=f"#{r['id']} — {time_str}",
                value=r["content"][:100],
                inline=False)
        embed.set_footer(text=f"Use /remindcancel <id> to cancel one • {config.FOOTER_TEXT}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /remindcancel ─────────────────────────────────────────

    @app_commands.command(name="remindcancel", description="Cancel an active reminder by ID.")
    @app_commands.describe(reminder_id="The reminder ID (from /reminders)")
    async def remindcancel(self, interaction: discord.Interaction, reminder_id: int):
        deleted = await db.delete_reminder(reminder_id, interaction.user.id)
        if not deleted:
            await interaction.response.send_message(
                embed=error_embed("Not Found",
                    f"No active reminder `#{reminder_id}` found for you."),
                ephemeral=True)
            return
        await interaction.response.send_message(
            embed=success_embed("Cancelled", f"Reminder `#{reminder_id}` has been cancelled."),
            ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Reminders(bot))
