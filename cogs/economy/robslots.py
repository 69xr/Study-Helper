import discord, random
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone, timedelta
from utils import db
from utils.helpers import error_embed
import aiosqlite, config

CURRENCY = "🪙"
ROB_COOLDOWN: dict[tuple, datetime] = {}
SLOTS_COOLDOWN: dict[tuple, datetime] = {}

SLOT_SYMBOLS = ["🍒", "🍋", "🍊", "🍇", "⭐", "💎", "7️⃣"]
SLOT_WEIGHTS  = [30,   25,   20,   15,   6,    3,    1  ]
SLOT_PAYOUTS  = {  # multiplier of bet
    "🍒": 1.5, "🍋": 2, "🍊": 2.5, "🍇": 3, "⭐": 5, "💎": 10, "7️⃣": 25
}


def _spin():
    return random.choices(SLOT_SYMBOLS, weights=SLOT_WEIGHTS, k=3)


class RobSlots(commands.Cog):
    def __init__(self, bot): self.bot = bot

    # ── /rob ──────────────────────────────────────────────
    @app_commands.command(name="rob", description="Attempt to rob another user's wallet.")
    @app_commands.describe(user="Who to rob")
    async def rob(self, interaction: discord.Interaction, user: discord.Member):
        if user.id == interaction.user.id:
            await interaction.response.send_message(embed=error_embed("Really?", "You can't rob yourself."), ephemeral=True)
            return
        if user.bot:
            await interaction.response.send_message(embed=error_embed("Invalid", "You can't rob a bot."), ephemeral=True)
            return

        key = (interaction.guild_id, interaction.user.id)
        now = datetime.now(timezone.utc)
        last = ROB_COOLDOWN.get(key)
        if last and (now - last) < timedelta(hours=1):
            remaining = 60 - int((now - last).seconds / 60)
            await interaction.response.send_message(
                embed=error_embed("Too Soon", f"Wait `{remaining}m` before robbing again."), ephemeral=True)
            return

        robber_data = await db.get_balance(interaction.guild_id, interaction.user.id)
        victim_data = await db.get_balance(interaction.guild_id, user.id)

        if victim_data["balance"] < 50:
            await interaction.response.send_message(
                embed=error_embed("Not Worth It", f"{user.display_name} has less than 50 {CURRENCY}. Not worth the risk!"),
                ephemeral=True)
            return

        ROB_COOLDOWN[key] = now
        success = random.random() < 0.4  # 40% success rate

        if success:
            stolen = random.randint(
                max(1, victim_data["balance"] // 10),
                max(1, victim_data["balance"] // 3)
            )
            # Transfer coins
            async with aiosqlite.connect(config.DB_PATH) as db_conn:
                await db_conn.execute(
                    "UPDATE economy SET balance=balance-? WHERE guild_id=? AND user_id=?",
                    (stolen, interaction.guild_id, user.id))
                await db_conn.execute(
                    "UPDATE economy SET balance=balance+? WHERE guild_id=? AND user_id=?",
                    (stolen, interaction.guild_id, interaction.user.id))
                await db_conn.execute(
                    "INSERT INTO transactions (guild_id,user_id,amount,type,note) VALUES (?,?,?,?,?)",
                    (interaction.guild_id, interaction.user.id, stolen, "rob", f"Robbed {user}"))
                await db_conn.commit()

            embed = discord.Embed(
                title="💰 Heist Successful!",
                description=(
                    f"You snuck up on {user.mention} and grabbed their wallet!\n"
                    f"You stole **{stolen:,}** {CURRENCY} and got away clean!"
                ),
                color=0x57F287
            )
            embed.set_footer(text="1h cooldown • 40% success rate")
        else:
            # Failed — pay a fine
            fine = random.randint(50, min(200, max(50, robber_data["balance"] // 5)))
            fine = min(fine, robber_data["balance"])
            if fine > 0:
                async with aiosqlite.connect(config.DB_PATH) as db_conn:
                    await db_conn.execute(
                        "UPDATE economy SET balance=MAX(0,balance-?) WHERE guild_id=? AND user_id=?",
                        (fine, interaction.guild_id, interaction.user.id))
                    await db_conn.commit()

            embed = discord.Embed(
                title="🚔 Caught Red-Handed!",
                description=(
                    f"You tried to rob {user.mention} but got caught!\n"
                    f"You were fined **{fine:,}** {CURRENCY}."
                ),
                color=0xED4245
            )
            embed.set_footer(text="1h cooldown • 40% success rate")

        await interaction.response.send_message(embed=embed)

    # ── /slots ─────────────────────────────────────────────
    @app_commands.command(name="slots", description="Play the slot machine!")
    @app_commands.describe(bet="Amount to bet (min 10)")
    async def slots(self, interaction: discord.Interaction,
                    bet: app_commands.Range[int, 10, 10000] = 50):
        key = (interaction.guild_id, interaction.user.id)
        now = datetime.now(timezone.utc)
        last = SLOTS_COOLDOWN.get(key)
        if last and (now - last) < timedelta(seconds=30):
            await interaction.response.send_message(
                embed=error_embed("Too Fast", "Wait 30 seconds between spins."), ephemeral=True)
            return

        data = await db.get_balance(interaction.guild_id, interaction.user.id)
        if data["balance"] < bet:
            await interaction.response.send_message(
                embed=error_embed("Insufficient Funds", f"You need `{bet:,}` {CURRENCY} to play."), ephemeral=True)
            return

        SLOTS_COOLDOWN[key] = now
        reels = _spin()
        display = " | ".join(reels)

        won = 0
        result_text = ""
        if reels[0] == reels[1] == reels[2]:  # Jackpot - all 3 match
            multiplier = SLOT_PAYOUTS.get(reels[0], 2)
            won = int(bet * multiplier)
            result_text = f"🎰 **JACKPOT!** All three match! Won `{won:,}` {CURRENCY}!"
            color = 0xffaa3d
        elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:  # 2 match
            won = int(bet * 0.5)
            result_text = f"✨ Two match! Won back `{won:,}` {CURRENCY}!"
            color = 0x57F287
        else:
            won = 0
            result_text = f"❌ No match. Lost `{bet:,}` {CURRENCY}."
            color = 0xED4245

        net = won - bet
        async with aiosqlite.connect(config.DB_PATH) as db_conn:
            await db_conn.execute(
                "UPDATE economy SET balance=MAX(0,balance+?) WHERE guild_id=? AND user_id=?",
                (net, interaction.guild_id, interaction.user.id))
            await db_conn.execute(
                "INSERT INTO transactions (guild_id,user_id,amount,type,note) VALUES (?,?,?,?,?)",
                (interaction.guild_id, interaction.user.id, net, "slots", f"Bet: {bet}"))
            await db_conn.commit()
            async with db_conn.execute("SELECT balance FROM economy WHERE guild_id=? AND user_id=?",
                                        (interaction.guild_id, interaction.user.id)) as c:
                new_bal = (await c.fetchone())[0]

        embed = discord.Embed(
            title="🎰 Slot Machine",
            description=f"**[ {display} ]**\n\n{result_text}",
            color=color
        )
        embed.add_field(name="Bet",     value=f"`{bet:,}` {CURRENCY}", inline=True)
        embed.add_field(name="Result",  value=f"`{'+' if net >= 0 else ''}{net:,}` {CURRENCY}", inline=True)
        embed.add_field(name="Balance", value=f"`{new_bal:,}` {CURRENCY}", inline=True)
        embed.set_footer(text="Tip: 💎 gives 10x, 7️⃣ gives 25x! • 30s cooldown")
        await interaction.response.send_message(embed=embed)

async def setup(bot): await bot.add_cog(RobSlots(bot))
