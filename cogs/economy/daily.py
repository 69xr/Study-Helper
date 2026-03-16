import discord, random
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone, timedelta
from utils import db

CURRENCY = "🪙"
DAILY_MIN, DAILY_MAX  = 150, 300
WORK_MIN,  WORK_MAX   = 30,  100
WORK_COOLDOWN_H       = 1

WORK_PHRASES = [
    "You fixed some bugs for a client", "You delivered packages all day",
    "You streamed for 3 hours", "You sold handmade crafts online",
    "You walked dogs in the neighborhood", "You won a poker game",
    "You found some coins in your couch", "You completed a freelance project",
    "You busked on the street corner", "You won a coding competition",
    "You tutored a student online", "You sold some old stuff on eBay",
]

def _hours_until(ts_str, hours):
    if not ts_str: return None
    try:
        past = datetime.fromisoformat(ts_str.replace("Z",""))
        if past.tzinfo is None: past = past.replace(tzinfo=timezone.utc)
        wait = (past + timedelta(hours=hours) - datetime.now(timezone.utc)).total_seconds() / 3600
        return max(0, wait)
    except: return None

class Daily(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="daily", description="Claim your daily coin reward.")
    async def daily(self, interaction: discord.Interaction):
        data = await db.get_balance(interaction.guild_id, interaction.user.id)
        wait = _hours_until(data.get("last_daily"), 24)
        if wait and wait > 0:
            h, m = int(wait), int((wait % 1) * 60)
            await interaction.response.send_message(
                embed=discord.Embed(description=f"⏰ Next daily in **{h}h {m}m**.", color=0xED4245),
                ephemeral=True)
            return
        amount  = random.randint(DAILY_MIN, DAILY_MAX)
        new_bal = await db.add_coins(interaction.guild_id, interaction.user.id, amount, "daily")
        await db.set_last_daily(interaction.guild_id, interaction.user.id)
        embed = discord.Embed(title="📅 Daily Claimed!", color=0xffaa3d)
        embed.add_field(name="Received", value=f"`+{amount}` {CURRENCY}", inline=True)
        embed.add_field(name="Balance",  value=f"`{new_bal:,}` {CURRENCY}", inline=True)
        embed.set_footer(text="Come back in 24 hours!")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="work", description="Work to earn coins (1h cooldown).")
    async def work(self, interaction: discord.Interaction):
        data = await db.get_balance(interaction.guild_id, interaction.user.id)
        wait = _hours_until(data.get("last_work"), WORK_COOLDOWN_H)
        if wait and wait > 0:
            m = int(wait * 60)
            await interaction.response.send_message(
                embed=discord.Embed(description=f"⏰ You can work again in **{m}m**.", color=0xED4245),
                ephemeral=True)
            return
        amount  = random.randint(WORK_MIN, WORK_MAX)
        phrase  = random.choice(WORK_PHRASES)
        new_bal = await db.add_coins(interaction.guild_id, interaction.user.id, amount, "work", phrase)
        await db.set_last_work(interaction.guild_id, interaction.user.id)
        embed = discord.Embed(title="💼 Work Complete",
                               description=f"{phrase} and earned **{amount}** {CURRENCY}!", color=0x3dffaa)
        embed.add_field(name="Balance", value=f"`{new_bal:,}` {CURRENCY}", inline=True)
        embed.set_footer(text=f"Cooldown: {WORK_COOLDOWN_H}h")
        await interaction.response.send_message(embed=embed)

async def setup(bot): await bot.add_cog(Daily(bot))
