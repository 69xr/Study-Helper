import discord, aiosqlite
from discord import app_commands
from discord.ext import commands
from utils import db
from utils.helpers import success_embed, error_embed
import config

CURRENCY = "🪙"
eco_group = app_commands.Group(name="eco", description="Economy admin commands.")

class EcoAdmin(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @eco_group.command(name="give", description="[Admin] Give coins to a user.")
    @app_commands.describe(user="Target user", amount="Amount to give")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def eco_give(self, interaction: discord.Interaction,
                        user: discord.Member, amount: app_commands.Range[int, 1, 10_000_000]):
        new_bal = await db.add_coins(interaction.guild_id, user.id, amount, "admin", f"Given by {interaction.user}")
        await interaction.response.send_message(
            embed=success_embed("Coins Given", f"Gave **{amount:,}** {CURRENCY} to {user.mention}.\nBalance: `{new_bal:,}`"),
            ephemeral=True)

    @eco_group.command(name="take", description="[Admin] Remove coins from a user.")
    @app_commands.describe(user="Target user", amount="Amount to remove")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def eco_take(self, interaction: discord.Interaction,
                        user: discord.Member, amount: app_commands.Range[int, 1, 10_000_000]):
        new_bal = await db.add_coins(interaction.guild_id, user.id, -amount, "admin", f"Taken by {interaction.user}")
        await interaction.response.send_message(
            embed=success_embed("Coins Taken", f"Took **{amount:,}** {CURRENCY} from {user.mention}.\nBalance: `{new_bal:,}`"),
            ephemeral=True)

    @eco_group.command(name="reset", description="[Admin] Reset a user's economy data.")
    @app_commands.describe(user="User to reset")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def eco_reset(self, interaction: discord.Interaction, user: discord.Member):
        async with aiosqlite.connect(config.DB_PATH) as db_conn:
            await db_conn.execute(
                "UPDATE economy SET balance=0,bank=0,total_earned=0,last_daily=NULL,last_work=NULL WHERE guild_id=? AND user_id=?",
                (interaction.guild_id, user.id))
            await db_conn.commit()
        await interaction.response.send_message(
            embed=success_embed("Reset", f"{user.mention}'s economy reset."), ephemeral=True)

    @eco_group.command(name="additem", description="[Admin] Add an item to the shop.")
    @app_commands.describe(name="Item name", price="Price in coins", description="Description",
                           role="Role to give on purchase", stock="Stock (-1=unlimited)", emoji="Emoji")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def eco_additem(self, interaction: discord.Interaction,
                           name: str, price: int, description: str = "",
                           role: discord.Role = None, stock: int = -1, emoji: str = "🛍️"):
        item_id = await db.add_shop_item(interaction.guild_id, name, description, price,
                                          role.id if role else None, stock, emoji)
        await interaction.response.send_message(
            embed=success_embed("Item Added", f"**{emoji} {name}** added (ID: `{item_id}`, Price: `{price:,}` {CURRENCY})"),
            ephemeral=True)

    @eco_group.command(name="removeitem", description="[Admin] Remove an item from the shop.")
    @app_commands.describe(item_id="Item ID from /shop")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def eco_removeitem(self, interaction: discord.Interaction, item_id: int):
        ok = await db.remove_shop_item(item_id, interaction.guild_id)
        if not ok:
            await interaction.response.send_message(embed=error_embed("Not Found", f"No item `{item_id}`."), ephemeral=True)
            return
        await interaction.response.send_message(
            embed=success_embed("Removed", f"Item `{item_id}` removed."), ephemeral=True)

    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=error_embed("Missing Permissions"), ephemeral=True)

async def setup(bot):
    bot.tree.add_command(eco_group)
    await bot.add_cog(EcoAdmin(bot))
