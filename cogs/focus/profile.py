"""
FocusBeast — Profile Cog

Commands:
  /profile  — full profile card with stats and active pet
  /xp       — quick XP and level check (ephemeral)
  /streak   — check your daily focus streak
  /history  — last 5 completed sessions
  /rank     — your server rank by XP
"""

import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
from utils import db
from utils.focus_image_engine import RARITY_LABELS


def _level_from_xp(xp: int) -> int:
    return max(1, int(xp ** 0.45) // 5)


def _xp_for_next(level: int) -> int:
    return int(((level + 1) * 5) ** (1 / 0.45))


class ProfileCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── /profile ──────────────────────────────────────────────────────────────
    @app_commands.command(
        name="profile",
        description="Open a branded focus profile card",
    )
    @app_commands.describe(user="View another member's profile (optional)")
    async def profile(self, i: discord.Interaction,
                      user: Optional[discord.Member] = None):
        target = user or i.user
        u      = await db.get_focus_user(target.id)
        pet    = await db.get_active_focus_pet(target.id)
        streak = await db.get_focus_streak(target.id)

        buf   = self.bot.focus_image_engine.render_profile(
            target.display_name, u["xp"], u["coins"],
            u["total_focus"], u["sessions"],
            active_pet=dict(pet) if pet else None,
        )
        file  = discord.File(buf, filename="profile.png")

        level = _level_from_xp(u["xp"])
        xp_nxt = _xp_for_next(level)

        embed = discord.Embed(
            title=f"{target.display_name}'s Profile",
            color=0x5080FF,
        )
        embed.add_field(name="Level",      value=str(level),                  inline=True)
        embed.add_field(name="XP",         value=f"{u['xp']:,} / {xp_nxt:,}", inline=True)
        embed.add_field(name="Coins",      value=f"{u['coins']:,}",            inline=True)
        embed.add_field(name="Focus Time", value=f"{u['total_focus']:,} min",  inline=True)
        embed.add_field(name="Sessions",   value=str(u["sessions"]),            inline=True)
        embed.add_field(
            name="Streak",
            value=f"{streak['current']} day(s) 🔥 (best: {streak['longest']})",
            inline=True,
        )
        if pet:
            embed.add_field(
                name="Active Companion",
                value=(
                    f"**{pet['name']}** — "
                    f"{RARITY_LABELS.get(pet['rarity'], pet['rarity'])}, "
                    f"Lv.{pet['level']}"
                ),
                inline=False,
            )
        embed.set_image(url="attachment://profile.png")
        embed.set_footer(text="Use /timer to earn XP · /streak for streak details")
        await i.response.send_message(embed=embed, file=file)

    # ── /xp ───────────────────────────────────────────────────────────────────
    @app_commands.command(name="focusxp", description="Check your focus XP progress and level")
    async def xp(self, i: discord.Interaction):
        u     = await db.get_focus_user(i.user.id)
        level = _level_from_xp(u["xp"])
        nxt   = _xp_for_next(level)
        prev  = _xp_for_next(level - 1) if level > 1 else 0
        prog  = u["xp"] - prev
        needed = nxt - prev
        bar_filled = int(20 * prog / max(needed, 1))
        bar = "█" * bar_filled + "░" * (20 - bar_filled)

        embed = discord.Embed(
            title=f"{i.user.display_name}  —  Level {level}",
            description=(
                f"`{bar}` {prog:,} / {needed:,}\n\n"
                f"**Total XP:** {u['xp']:,}\n"
                f"**Coins:**    {u['coins']:,}"
            ),
            color=0xFFD700,
        )
        embed.set_footer(text="Use /timer to earn XP and level up")
        await i.response.send_message(embed=embed, ephemeral=True)

    # ── /streak ───────────────────────────────────────────────────────────────
    @app_commands.command(
        name="streak", description="Review your daily focus streak"
    )
    async def streak(self, i: discord.Interaction):
        s = await db.get_focus_streak(i.user.id)
        cur = s["current"]
        lng = s["longest"]
        last = s.get("last_session", "Never")

        if cur == 0:
            blurb = "Complete a session today to start your streak!"
        elif cur < 3:
            blurb = "Good start! Keep it going."
        elif cur < 7:
            blurb = "You're on a roll! Don't break the chain."
        elif cur < 14:
            blurb = "One week+ streak — impressive!"
        else:
            blurb = "Unstoppable. Absolute legend."

        embed = discord.Embed(
            title=f"{i.user.display_name}'s Streak",
            description=(
                f"**Current streak:** {cur} day(s) 🔥\n"
                f"**Longest streak:** {lng} day(s)\n"
                f"**Last session:** {last}\n\n"
                f"*{blurb}*"
            ),
            color=0xFF8C00 if cur > 0 else 0x555555,
        )
        embed.set_footer(
            text="Complete at least one focus session per day to maintain your streak"
        )
        await i.response.send_message(embed=embed, ephemeral=True)

    # ── /history ──────────────────────────────────────────────────────────────
    @app_commands.command(
        name="history", description="Review your five most recent completed focus sessions"
    )
    async def history(self, i: discord.Interaction):
        rows = await db.get_focus_session_history(i.user.id, 5)
        if not rows:
            return await i.response.send_message(
                "No completed sessions yet — use `/timer` to get started!",
                ephemeral=True,
            )
        lines = []
        for r in rows:
            lines.append(
                f"**{r['duration']} min** · {r['theme']} · "
                f"+{r['xp_earned']} XP, +{r['coins_earned']} coins · "
                f"`{r['completed_at'][:16]}`"
            )
        embed = discord.Embed(
            title="Recent Sessions",
            description="\n".join(lines),
            color=0x5080FF,
        )
        embed.set_footer(text="Showing your 5 most recent completed sessions")
        await i.response.send_message(embed=embed, ephemeral=True)

    # ── /rank ─────────────────────────────────────────────────────────────────
    @app_commands.command(
        name="focusrank", description="See where you rank by focus XP in this server"
    )
    async def rank(self, i: discord.Interaction):
        rows = await db.get_focus_leaderboard(200)
        uid  = i.user.id
        pos  = next((idx + 1 for idx, r in enumerate(rows) if r["user_id"] == uid), None)
        u    = await db.get_focus_user(uid)

        if pos is None:
            return await i.response.send_message(
                "You're not on the leaderboard yet — complete a session first!",
                ephemeral=True,
            )

        level = _level_from_xp(u["xp"])
        embed = discord.Embed(
            title=f"{i.user.display_name}'s Rank",
            description=(
                f"**Server rank: #{pos}** out of {len(rows)}\n\n"
                f"**XP:** {u['xp']:,}  ·  **Level:** {level}\n"
                f"**Coins:** {u['coins']:,}\n"
                f"**Sessions:** {u['sessions']}"
            ),
            color=0xFFD700,
        )
        if pos == 1:
            embed.description += "\n\n👑 You are #1 — the top grinder!"
        elif pos <= 3:
            embed.description += f"\n\n🏆 You're in the top 3!"
        elif pos <= 10:
            embed.description += f"\n\n🎯 You're in the top 10!"
        embed.set_footer(text="Use /focusrank to check your focus standing")
        await i.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ProfileCog(bot))
