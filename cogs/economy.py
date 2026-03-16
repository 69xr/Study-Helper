"""
cogs/economy.py
Commands: /balance /daily /work /pay /leaderboard /shop /buy /inventory
          /eco give /eco take /eco reset /eco additem /eco removeitem  (admin)
"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone, timedelta
import random
from utils import db
from utils.helpers import error_embed, success_embed

# ── Config ────────────────────────────────────────────
DAILY_MIN    = 150
DAILY_MAX    = 300
WORK_MIN     = 30
WORK_MAX     = 100
WORK_COOLDOWN_H = 1   # hours
CURRENCY     = "🪙"

WORK_PHRASES = [
    "You fixed some bugs for a client", "You delivered packages all day",
    "You streamed for 3 hours", "You sold handmade crafts online",
    "You walked dogs in the neighborhood", "You won a poker game",
    "You found some coins in your couch", "You completed a freelance project",
    "You busked on the street corner", "You won a coding competition",
]

eco_group   = app_commands.Group(name="eco",  description="Economy admin commands.")



def _hours_until(ts_str: str, hours: int) -> float | None:
    if not ts_str: return None
    try:
        past = datetime.fromisoformat(ts_str.replace("Z",""))
        if past.tzinfo is None: past = past.replace(tzinfo=timezone.utc)
        ready = past + timedelta(hours=hours)
        now   = datetime.now(timezone.utc)
        return max(0, (ready - now).total_seconds() / 3600)
    except:
        return None


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /balance ─────────────────────────────────────────────
    @app_commands.command(name="balance", description="Check your or another user's balance.")
    @app_commands.describe(user="User to check (default: yourself)")
    async def balance(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        data   = await db.get_balance(interaction.guild_id, target.id)
        rank_data = await db.get_leaderboard(interaction.guild_id, 100)
        rank = next((i+1 for i, r in enumerate(rank_data) if str(r["user_id"]) == str(target.id)), "—")

        embed = discord.Embed(title=f"{CURRENCY} {target.display_name}'s Wallet", color=0xffaa3d)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name=f"{CURRENCY} Wallet",  value=f"`{data['balance']:,}`",      inline=True)
        embed.add_field(name="🏦 Bank",             value=f"`{data['bank']:,}`",         inline=True)
        embed.add_field(name="💎 Total Earned",     value=f"`{data['total_earned']:,}`", inline=True)
        embed.add_field(name="🏆 Server Rank",      value=f"`#{rank}`",                  inline=True)
        embed.set_footer(text=f"Net worth: {data['balance']+data['bank']:,} {CURRENCY}")
        await interaction.response.send_message(embed=embed)

    # ── /daily ───────────────────────────────────────────────
    @app_commands.command(name="daily", description="Claim your daily coins.")
    async def daily(self, interaction: discord.Interaction):
        data = await db.get_balance(interaction.guild_id, interaction.user.id)
        wait = _hours_until(data.get("last_daily"), 24)
        if wait and wait > 0:
            h, m = int(wait), int((wait % 1) * 60)
            await interaction.response.send_message(
                embed=error_embed("Already Claimed", f"Next daily in **{h}h {m}m**."), ephemeral=True
            )
            return

        amount = random.randint(DAILY_MIN, DAILY_MAX)
        new_bal = await db.add_coins(interaction.guild_id, interaction.user.id, amount, "daily")
        await db.set_last_daily(interaction.guild_id, interaction.user.id)

        embed = discord.Embed(title="📅 Daily Claimed!", color=0xffaa3d)
        embed.add_field(name="Received",  value=f"`+{amount}` {CURRENCY}", inline=True)
        embed.add_field(name="Balance",   value=f"`{new_bal:,}` {CURRENCY}", inline=True)
        embed.set_footer(text="Come back in 24 hours!")
        await interaction.response.send_message(embed=embed)

    # ── /work ────────────────────────────────────────────────
    @app_commands.command(name="work", description="Work to earn some coins.")
    async def work(self, interaction: discord.Interaction):
        data = await db.get_balance(interaction.guild_id, interaction.user.id)
        wait = _hours_until(data.get("last_work"), WORK_COOLDOWN_H)
        if wait and wait > 0:
            m = int(wait * 60)
            await interaction.response.send_message(
                embed=error_embed("Still Working", f"You can work again in **{m}m**."), ephemeral=True
            )
            return

        amount  = random.randint(WORK_MIN, WORK_MAX)
        phrase  = random.choice(WORK_PHRASES)
        new_bal = await db.add_coins(interaction.guild_id, interaction.user.id, amount, "work", phrase)
        await db.set_last_work(interaction.guild_id, interaction.user.id)

        embed = discord.Embed(
            title="💼 Work Complete",
            description=f"{phrase} and earned **{amount}** {CURRENCY}!",
            color=0x3dffaa
        )
        embed.add_field(name="Balance", value=f"`{new_bal:,}` {CURRENCY}", inline=True)
        embed.set_footer(text=f"Cooldown: {WORK_COOLDOWN_H}h")
        await interaction.response.send_message(embed=embed)

    # ── /pay ─────────────────────────────────────────────────
    @app_commands.command(name="pay", description="Transfer coins to another user.")
    @app_commands.describe(user="Who to pay", amount="Amount to transfer")
    async def pay(self, interaction: discord.Interaction,
                  user: discord.Member, amount: app_commands.Range[int, 1, 1000000]):
        if user.id == interaction.user.id:
            await interaction.response.send_message(
                embed=error_embed("Invalid", "You can't pay yourself."), ephemeral=True
            )
            return
        if user.bot:
            await interaction.response.send_message(
                embed=error_embed("Invalid", "You can't pay a bot."), ephemeral=True
            )
            return

        ok = await db.transfer_coins(interaction.guild_id, interaction.user.id, user.id, amount)
        if not ok:
            await interaction.response.send_message(
                embed=error_embed("Insufficient Funds", f"You don't have `{amount:,}` {CURRENCY}."), ephemeral=True
            )
            return

        embed = discord.Embed(title=f"{CURRENCY} Transfer Complete", color=0x3dffaa)
        embed.add_field(name="From",   value=interaction.user.mention, inline=True)
        embed.add_field(name="To",     value=user.mention,             inline=True)
        embed.add_field(name="Amount", value=f"`{amount:,}` {CURRENCY}", inline=True)
        await interaction.response.send_message(embed=embed)

    # ── /leaderboard ─────────────────────────────────────────
    @app_commands.command(name="leaderboard", description="See the richest members.")
    async def leaderboard(self, interaction: discord.Interaction):
        board = await db.get_leaderboard(interaction.guild_id, 10)
        if not board:
            await interaction.response.send_message(
                embed=error_embed("Empty", "No economy data yet."), ephemeral=True
            )
            return
        embed = discord.Embed(title=f"💰 {interaction.guild.name} — Leaderboard", color=0xffaa3d)
        medals = ["🥇","🥈","🥉"]
        lines = []
        for i, row in enumerate(board):
            member = interaction.guild.get_member(row["user_id"])
            name   = member.display_name if member else f"User {row['user_id']}"
            medal  = medals[i] if i < 3 else f"`#{i+1}`"
            net    = row["balance"] + row["bank"]
            lines.append(f"{medal} **{name}** — `{net:,}` {CURRENCY}")
        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)

    # ── /inventory ───────────────────────────────────────────
    @app_commands.command(name="inventory", description="View your inventory.")
    async def inventory(self, interaction: discord.Interaction):
        items = await db.get_inventory(interaction.guild_id, interaction.user.id)
        embed = discord.Embed(title=f"🎒 {interaction.user.display_name}'s Inventory", color=0x3d8bff)
        if not items:
            embed.description = "Your inventory is empty. Check out `/shop` to buy something!"
        else:
            lines = [f"{i['emoji']} **{i['name']}** x{i['quantity']} — {i['description']}" for i in items]
            embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── SHOP subgroup ─────────────────────────────────────────
    @app_commands.command(name="shop", description="Browse the server shop.")
    async def shop(self, interaction: discord.Interaction):
        items = await db.get_shop(interaction.guild_id)
        embed = discord.Embed(title=f"🛍️ {interaction.guild.name} Shop", color=0xffaa3d)
        if not items:
            embed.description = "The shop is empty. Admins can add items with `/eco additem`."
        else:
            for item in items:
                stock = f"Stock: {item['stock']}" if item["stock"] != -1 else "Unlimited"
                embed.add_field(
                    name=f"{item['emoji']} {item['name']} — {item['price']:,} {CURRENCY}",
                    value=f"{item['description'] or 'No description'}\n`ID: {item['id']}` · {stock}",
                    inline=False
                )
        embed.set_footer(text="Use /buy <id> to purchase.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="buy", description="Buy an item from the shop.")
    @app_commands.describe(item_id="Item ID from /shop")
    async def buy(self, interaction: discord.Interaction, item_id: int):
        ok, result = await db.buy_item(interaction.guild_id, interaction.user.id, item_id)
        if not ok:
            await interaction.response.send_message(embed=error_embed("Purchase Failed", result), ephemeral=True)
            return

        # Give role if item has one
        if result:  # result is role_id
            role = interaction.guild.get_role(int(result))
            if role:
                try: await interaction.user.add_roles(role, reason="Shop purchase")
                except: pass

        await interaction.response.send_message(
            embed=success_embed("Purchased!", "Item added to your inventory. Check `/inventory`."),
            ephemeral=True
        )

    # ── ECO ADMIN subgroup ────────────────────────────────────
    @eco_group.command(name="give", description="[Admin] Give coins to a user.")
    @app_commands.describe(user="Target user", amount="Amount to give")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def eco_give(self, interaction: discord.Interaction,
                        user: discord.Member, amount: app_commands.Range[int, 1, 10000000]):
        new_bal = await db.add_coins(interaction.guild_id, user.id, amount, "admin", f"Given by {interaction.user}")
        await interaction.response.send_message(
            embed=success_embed("Coins Given", f"Gave **{amount:,}** {CURRENCY} to {user.mention}.\nNew balance: `{new_bal:,}`"),
            ephemeral=True
        )

    @eco_group.command(name="take", description="[Admin] Remove coins from a user.")
    @app_commands.describe(user="Target user", amount="Amount to remove")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def eco_take(self, interaction: discord.Interaction,
                        user: discord.Member, amount: app_commands.Range[int, 1, 10000000]):
        new_bal = await db.add_coins(interaction.guild_id, user.id, -amount, "admin", f"Taken by {interaction.user}")
        await interaction.response.send_message(
            embed=success_embed("Coins Taken", f"Took **{amount:,}** {CURRENCY} from {user.mention}.\nNew balance: `{new_bal:,}`"),
            ephemeral=True
        )

    @eco_group.command(name="reset", description="[Admin] Reset a user's economy data.")
    @app_commands.describe(user="User to reset")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def eco_reset(self, interaction: discord.Interaction, user: discord.Member):
        from config import DB_PATH
        import aiosqlite
        async with aiosqlite.connect(DB_PATH) as db_conn:
            await db_conn.execute(
                "UPDATE economy SET balance=0,bank=0,total_earned=0,last_daily=NULL,last_work=NULL WHERE guild_id=? AND user_id=?",
                (interaction.guild_id, user.id)
            )
            await db_conn.commit()
        await interaction.response.send_message(
            embed=success_embed("Reset", f"{user.mention}'s economy has been reset."), ephemeral=True
        )

    @eco_group.command(name="additem", description="[Admin] Add an item to the shop.")
    @app_commands.describe(
        name="Item name", price="Price in coins",
        description="Item description", role="Role to give on purchase",
        stock="Stock (-1 = unlimited)", emoji="Item emoji"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def eco_additem(self, interaction: discord.Interaction,
                           name: str, price: int, description: str = "",
                           role: discord.Role = None, stock: int = -1, emoji: str = "🛍️"):
        item_id = await db.add_shop_item(
            interaction.guild_id, name, description, price,
            role.id if role else None, stock, emoji
        )
        await interaction.response.send_message(
            embed=success_embed("Item Added", f"**{emoji} {name}** added to shop with ID `{item_id}`.\nPrice: `{price:,}` {CURRENCY}"),
            ephemeral=True
        )

    @eco_group.command(name="removeitem", description="[Admin] Remove an item from the shop.")
    @app_commands.describe(item_id="Item ID from /shop")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def eco_removeitem(self, interaction: discord.Interaction, item_id: int):
        ok = await db.remove_shop_item(item_id, interaction.guild_id)
        if not ok:
            await interaction.response.send_message(
                embed=error_embed("Not Found", f"No item with ID `{item_id}` in this server's shop."), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=success_embed("Removed", f"Item `{item_id}` removed from shop."), ephemeral=True
        )


async def setup(bot: commands.Bot):
    cog = Economy(bot)
    bot.tree.add_command(eco_group)
    await bot.add_cog(cog)
