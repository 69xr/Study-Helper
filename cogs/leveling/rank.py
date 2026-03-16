import discord, json, random
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone, timedelta
from utils import db

def xp_needed(level): return 5*(level**2) + 50*level + 100
def total_xp_for(level): return sum(xp_needed(i) for i in range(level))
def make_bar(cur, needed, length=20):
    pct = min(1.0, cur / max(1, needed))
    f   = int(pct * length)
    return "█" * f + "░" * (length - f)

class Rank(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._cooldowns: dict[tuple, datetime] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not message.content: return
        settings = await db.get_level_settings(message.guild.id)
        if not settings["enabled"]: return
        no_xp_channels = json.loads(settings["no_xp_channels"] or "[]")
        no_xp_roles    = json.loads(settings["no_xp_roles"]    or "[]")
        if message.channel.id in no_xp_channels: return
        if any(r.id in no_xp_roles for r in message.author.roles): return
        key      = (message.guild.id, message.author.id)
        now      = datetime.now(timezone.utc)
        cooldown = timedelta(seconds=settings["xp_cooldown"])
        last     = self._cooldowns.get(key)
        if last and (now - last) < cooldown: return
        self._cooldowns[key] = now
        if len(self._cooldowns) % 500 == 0:
            cutoff = now - timedelta(hours=2)
            self._cooldowns = {k: v for k, v in self._cooldowns.items() if v > cutoff}
        xp_gained = random.randint(settings["xp_min"], settings["xp_max"])
        result    = await db.add_xp(message.guild.id, message.author.id, xp_gained)
        if result["leveled_up"]:
            await self._level_up(message, result["new_level"], settings)

    async def _level_up(self, message, new_level, settings):
        lvl_ch  = message.guild.get_channel(settings.get("level_up_channel") or 0) or message.channel
        template = settings.get("level_up_msg") or "GG {user}! You reached **Level {level}** 🎉"
        text     = template.replace("{user}", message.author.mention).replace("{level}", str(new_level))
        embed    = discord.Embed(description=text, color=0xffaa3d)
        embed.set_thumbnail(url=message.author.display_avatar.url)
        try: await lvl_ch.send(embed=embed)
        except discord.Forbidden: pass
        for lr in await db.get_level_roles(message.guild.id):
            if lr["level"] <= new_level:
                role = message.guild.get_role(lr["role_id"])
                if role and role not in message.author.roles:
                    try: await message.author.add_roles(role, reason=f"Level {lr['level']} reward")
                    except: pass

    @app_commands.command(name="rank", description="View your or another user's XP rank.")
    @app_commands.describe(user="User to check (default: yourself)")
    async def rank(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        data   = await db.get_user_level(interaction.guild_id, target.id)
        rank_n = await db.get_user_rank(interaction.guild_id, target.id)
        needed = xp_needed(data["level"])
        bar    = make_bar(data["xp"], needed)
        embed  = discord.Embed(title=f"⭐ {target.display_name}", color=0xffaa3d)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Level",    value=f"`{data['level']}`",            inline=True)
        embed.add_field(name="Rank",     value=f"`#{rank_n}`",                  inline=True)
        embed.add_field(name="Messages", value=f"`{data['messages']:,}`",       inline=True)
        embed.add_field(name="Progress", value=f"`{bar}` `{data['xp']:,}/{needed:,} XP`", inline=False)
        embed.set_footer(text=f"Total XP: {total_xp_for(data['level']) + data['xp']:,}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="levels", description="View the XP leaderboard.")
    async def levels(self, interaction: discord.Interaction):
        board = await db.get_level_leaderboard(interaction.guild_id, 10)
        if not board:
            await interaction.response.send_message(
                embed=discord.Embed(description="No leveling data yet.", color=0xED4245), ephemeral=True)
            return
        medals = ["🥇","🥈","🥉"]
        embed  = discord.Embed(title=f"⭐ {interaction.guild.name} — Level Board", color=0xffaa3d)
        lines  = []
        for i, row in enumerate(board):
            m    = interaction.guild.get_member(row["user_id"])
            name = m.display_name if m else f"User {row['user_id']}"
            medal = medals[i] if i < 3 else f"`#{i+1}`"
            lines.append(f"{medal} **{name}** — Lvl `{row['level']}` · `{row['xp']:,}` XP")
        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)

async def setup(bot): await bot.add_cog(Rank(bot))
