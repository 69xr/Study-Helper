"""
cogs/leveling.py
Commands : /rank  /levels  /levelsetup  /setlevelrole  /removelevelrole  /resetxp
Events   : on_message (award XP with cooldown)
"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone, timedelta
import random
import json
from utils import db
from utils.helpers import success_embed, error_embed

def xp_needed(level: int) -> int:
    """XP needed to reach the NEXT level from current level."""
    return 5 * (level ** 2) + 50 * level + 100

def total_xp_for(level: int) -> int:
    """Cumulative XP needed to reach this level from 0."""
    return sum(xp_needed(i) for i in range(level))

def make_xp_bar(current_xp: int, needed_xp: int, length: int = 20) -> str:
    pct   = min(1.0, current_xp / max(1, needed_xp))
    filled = int(pct * length)
    return "█" * filled + "░" * (length - filled)


class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cooldowns: dict[tuple, datetime] = {}   # (guild_id, user_id) → last xp time

    # ── on_message: award XP ─────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild: return
        if not message.content: return

        settings = await db.get_level_settings(message.guild.id)
        if not settings["enabled"]: return

        # Check exempt channels / roles
        no_xp_channels = json.loads(settings["no_xp_channels"] or "[]")
        no_xp_roles    = json.loads(settings["no_xp_roles"]    or "[]")
        if message.channel.id in no_xp_channels: return
        if any(r.id in no_xp_roles for r in message.author.roles): return

        # Cooldown check with TTL eviction to prevent memory leak
        key      = (message.guild.id, message.author.id)
        now      = datetime.now(timezone.utc)
        cooldown = timedelta(seconds=settings["xp_cooldown"])
        last     = self._cooldowns.get(key)
        if last and (now - last) < cooldown:
            return
        self._cooldowns[key] = now

        # Prune stale entries every ~500 messages to prevent unbounded growth
        if len(self._cooldowns) % 500 == 0:
            cutoff = now - timedelta(hours=2)
            self._cooldowns = {k: v for k, v in self._cooldowns.items() if v > cutoff}

        # Award XP
        xp_gained = random.randint(settings["xp_min"], settings["xp_max"])
        result    = await db.add_xp(message.guild.id, message.author.id, xp_gained)

        if result["leveled_up"]:
            await self._handle_level_up(message, result["new_level"], settings)

    async def _handle_level_up(self, message: discord.Message, new_level: int, settings: dict):
        # Send level-up message
        lvl_ch_id = settings.get("level_up_channel")
        channel   = message.guild.get_channel(lvl_ch_id) if lvl_ch_id else message.channel

        msg_template = settings["level_up_msg"] or "GG {user}! You reached **Level {level}** 🎉"
        text = msg_template.replace("{user}", message.author.mention).replace("{level}", str(new_level))

        embed = discord.Embed(description=text, color=0xffaa3d)
        embed.set_thumbnail(url=message.author.display_avatar.url)
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass

        # Assign level roles
        level_roles = await db.get_level_roles(message.guild.id)
        for lr in level_roles:
            if lr["level"] <= new_level:
                role = message.guild.get_role(lr["role_id"])
                if role and role not in message.author.roles:
                    try: await message.author.add_roles(role, reason=f"Reached level {lr['level']}")
                    except: pass

    # ── /rank ─────────────────────────────────────────────────
    @app_commands.command(name="rank", description="Check your or another user's rank & XP.")
    @app_commands.describe(user="User to check (default: yourself)")
    async def rank(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        data   = await db.get_user_level(interaction.guild_id, target.id)
        rank_n = await db.get_user_rank(interaction.guild_id, target.id)
        needed = xp_needed(data["level"])

        embed = discord.Embed(
            title=f"⭐ {target.display_name}",
            color=0xffaa3d
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        bar = make_xp_bar(data["xp"], needed)
        embed.add_field(name="Level",    value=f"`{data['level']}`",             inline=True)
        embed.add_field(name="Rank",     value=f"`#{rank_n}`",                   inline=True)
        embed.add_field(name="Messages", value=f"`{data['messages']:,}`",        inline=True)
        embed.add_field(
            name="Progress",
            value=f"`{bar}` `{data['xp']:,}/{needed:,} XP`",
            inline=False
        )
        embed.set_footer(text=f"Total XP earned: {total_xp_for(data['level']) + data['xp']:,}")
        await interaction.response.send_message(embed=embed)

    # ── /levels ───────────────────────────────────────────────
    @app_commands.command(name="levels", description="View the XP leaderboard.")
    async def levels(self, interaction: discord.Interaction):
        board = await db.get_level_leaderboard(interaction.guild_id, 10)
        if not board:
            await interaction.response.send_message(
                embed=error_embed("Empty", "No leveling data yet. Start chatting!"), ephemeral=True
            )
            return

        medals = ["🥇","🥈","🥉"]
        embed = discord.Embed(title=f"⭐ {interaction.guild.name} — Level Leaderboard", color=0xffaa3d)
        lines = []
        for i, row in enumerate(board):
            member = interaction.guild.get_member(row["user_id"])
            name   = member.display_name if member else f"User {row['user_id']}"
            medal  = medals[i] if i < 3 else f"`#{i+1}`"
            lines.append(f"{medal} **{name}** — Lvl `{row['level']}` · `{row['xp']:,}` XP")
        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)

    # ── /levelsetup ───────────────────────────────────────────
    @app_commands.command(name="levelsetup", description="Configure the leveling system.")
    @app_commands.describe(
        enabled="Enable or disable leveling",
        xp_min="Minimum XP per message",
        xp_max="Maximum XP per message",
        cooldown="Cooldown in seconds between XP gains",
        level_up_channel="Channel for level-up announcements (empty = same channel)",
        level_up_msg="Level-up message. Use {user} and {level}"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def levelsetup(
        self,
        interaction: discord.Interaction,
        enabled: bool = None,
        xp_min: app_commands.Range[int, 1, 500] = None,
        xp_max: app_commands.Range[int, 1, 500] = None,
        cooldown: app_commands.Range[int, 5, 3600] = None,
        level_up_channel: discord.TextChannel = None,
        level_up_msg: str = None
    ):
        if enabled is not None:    await db.set_level_setting(interaction.guild_id, "enabled", int(enabled))
        if xp_min is not None:     await db.set_level_setting(interaction.guild_id, "xp_min", xp_min)
        if xp_max is not None:     await db.set_level_setting(interaction.guild_id, "xp_max", xp_max)
        if cooldown is not None:   await db.set_level_setting(interaction.guild_id, "xp_cooldown", cooldown)
        if level_up_channel:       await db.set_level_setting(interaction.guild_id, "level_up_channel", level_up_channel.id)
        if level_up_msg:           await db.set_level_setting(interaction.guild_id, "level_up_msg", level_up_msg)

        s = await db.get_level_settings(interaction.guild_id)
        lch = interaction.guild.get_channel(s["level_up_channel"]) if s["level_up_channel"] else None

        embed = success_embed("Leveling Configured")
        embed.add_field(name="Status",          value="✅ Enabled" if s["enabled"] else "❌ Disabled",     inline=True)
        embed.add_field(name="XP Range",        value=f"`{s['xp_min']}–{s['xp_max']}` per msg",           inline=True)
        embed.add_field(name="Cooldown",        value=f"`{s['xp_cooldown']}s`",                            inline=True)
        embed.add_field(name="Level-Up Channel",value=lch.mention if lch else "Same channel as message",   inline=True)
        embed.add_field(name="Level-Up Message",value=f"`{s['level_up_msg']}`",                            inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /setlevelrole ─────────────────────────────────────────
    @app_commands.command(name="setlevelrole", description="Assign a role to be given at a certain level.")
    @app_commands.describe(level="Level at which role is assigned", role="Role to give")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def setlevelrole(self, interaction: discord.Interaction,
                            level: app_commands.Range[int, 1, 500], role: discord.Role):
        await db.set_level_role(interaction.guild_id, level, role.id)
        await interaction.response.send_message(
            embed=success_embed("Level Role Set", f"{role.mention} will be given at Level **{level}**."),
            ephemeral=True
        )

    # ── /removelevelrole ──────────────────────────────────────
    @app_commands.command(name="removelevelrole", description="Remove the role reward for a level.")
    @app_commands.describe(level="Level to remove role from")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def removelevelrole(self, interaction: discord.Interaction, level: int):
        await db.remove_level_role(interaction.guild_id, level)
        await interaction.response.send_message(
            embed=success_embed("Removed", f"Level role for Level **{level}** removed."), ephemeral=True
        )

    # ── /resetxp ─────────────────────────────────────────────
    @app_commands.command(name="resetxp", description="[Admin] Reset a user's XP and level.")
    @app_commands.describe(user="User to reset")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def resetxp(self, interaction: discord.Interaction, user: discord.Member):
        from config import DB_PATH
        import aiosqlite
        async with aiosqlite.connect(DB_PATH) as db_conn:
            await db_conn.execute(
                "UPDATE levels SET xp=0,level=0,messages=0,last_xp=NULL WHERE guild_id=? AND user_id=?",
                (interaction.guild_id, user.id)
            )
            await db_conn.commit()
        await interaction.response.send_message(
            embed=success_embed("XP Reset", f"{user.mention}'s XP and level have been reset to 0."),
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Leveling(bot))
