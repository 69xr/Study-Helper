import discord
from discord import app_commands
from discord.ext import commands
from utils import db
from utils.helpers import success_embed, error_embed
import aiosqlite
import config

CURRENCY = "🪙"

class Bank(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="deposit", description="Deposit coins into your bank for safekeeping.")
    @app_commands.describe(amount="Amount to deposit (use 'all' for everything)")
    async def deposit(self, interaction: discord.Interaction, amount: str):
        data = await db.get_balance(interaction.guild_id, interaction.user.id)
        balance = data["balance"]

        if amount.lower() == "all":
            dep = balance
        else:
            try:
                dep = int(amount)
            except ValueError:
                await interaction.response.send_message(
                    embed=error_embed("Invalid Amount", "Enter a number or `all`."), ephemeral=True)
                return

        if dep <= 0:
            await interaction.response.send_message(embed=error_embed("Invalid", "Amount must be positive."), ephemeral=True)
            return
        if dep > balance:
            await interaction.response.send_message(
                embed=error_embed("Insufficient Funds", f"You only have `{balance:,}` {CURRENCY} in your wallet."), ephemeral=True)
            return

        async with aiosqlite.connect(config.DB_PATH) as db_conn:
            await db_conn.execute(
                "UPDATE economy SET balance=balance-?, bank=bank+? WHERE guild_id=? AND user_id=?",
                (dep, dep, interaction.guild_id, interaction.user.id))
            await db_conn.commit()
            async with db_conn.execute("SELECT balance, bank FROM economy WHERE guild_id=? AND user_id=?",
                                        (interaction.guild_id, interaction.user.id)) as c:
                row = await c.fetchone()

        embed = success_embed("🏦 Deposited!")
        embed.add_field(name="Deposited",       value=f"`{dep:,}` {CURRENCY}", inline=True)
        embed.add_field(name="💳 Wallet",       value=f"`{row[0]:,}` {CURRENCY}", inline=True)
        embed.add_field(name="🏦 Bank",         value=f"`{row[1]:,}` {CURRENCY}", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="withdraw", description="Withdraw coins from your bank.")
    @app_commands.describe(amount="Amount to withdraw (use 'all' for everything)")
    async def withdraw(self, interaction: discord.Interaction, amount: str):
        data = await db.get_balance(interaction.guild_id, interaction.user.id)
        bank = data["bank"]

        if amount.lower() == "all":
            wit = bank
        else:
            try:
                wit = int(amount)
            except ValueError:
                await interaction.response.send_message(
                    embed=error_embed("Invalid Amount", "Enter a number or `all`."), ephemeral=True)
                return

        if wit <= 0:
            await interaction.response.send_message(embed=error_embed("Invalid", "Amount must be positive."), ephemeral=True)
            return
        if wit > bank:
            await interaction.response.send_message(
                embed=error_embed("Insufficient Funds", f"You only have `{bank:,}` {CURRENCY} in your bank."), ephemeral=True)
            return

        async with aiosqlite.connect(config.DB_PATH) as db_conn:
            await db_conn.execute(
                "UPDATE economy SET balance=balance+?, bank=bank-? WHERE guild_id=? AND user_id=?",
                (wit, wit, interaction.guild_id, interaction.user.id))
            await db_conn.commit()
            async with db_conn.execute("SELECT balance, bank FROM economy WHERE guild_id=? AND user_id=?",
                                        (interaction.guild_id, interaction.user.id)) as c:
                row = await c.fetchone()

        embed = success_embed("🏦 Withdrawn!")
        embed.add_field(name="Withdrawn",  value=f"`{wit:,}` {CURRENCY}", inline=True)
        embed.add_field(name="💳 Wallet",  value=f"`{row[0]:,}` {CURRENCY}", inline=True)
        embed.add_field(name="🏦 Bank",    value=f"`{row[1]:,}` {CURRENCY}", inline=True)
        await interaction.response.send_message(embed=embed)

async def setup(bot): await bot.add_cog(Bank(bot))
