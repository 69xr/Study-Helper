import discord
from discord import app_commands
from discord.ext import commands
from utils import db

CURRENCY = "🪙"

class Shop(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="shop", description="Browse the server's item shop.")
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
                    inline=False)
        embed.set_footer(text="Use /buy <id> to purchase")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="buy", description="Buy an item from the shop.")
    @app_commands.describe(item_id="Item ID from /shop")
    async def buy(self, interaction: discord.Interaction, item_id: int):
        ok, result = await db.buy_item(interaction.guild_id, interaction.user.id, item_id)
        if not ok:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ {result}", color=0xED4245), ephemeral=True)
            return
        if result:  # role_id
            role = interaction.guild.get_role(int(result))
            if role:
                try: await interaction.user.add_roles(role, reason="Shop purchase")
                except: pass
        await interaction.response.send_message(
            embed=discord.Embed(description="✅ Purchased! Check `/inventory`.", color=0x57F287), ephemeral=True)

async def setup(bot): await bot.add_cog(Shop(bot))
