import discord
from discord import app_commands
from discord.ext import commands
from utils import db

CURRENCY = "🪙"

class Balance(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="balance", description="Check your or another user's coin balance.")
    @app_commands.describe(user="User to check (default: yourself)")
    async def balance(self, interaction: discord.Interaction, user: discord.Member = None):
        target    = user or interaction.user
        data      = await db.get_balance(interaction.guild_id, target.id)
        rank_list = await db.get_leaderboard(interaction.guild_id, 100)
        rank      = next((i+1 for i,r in enumerate(rank_list) if str(r["user_id"]) == str(target.id)), "—")
        net       = data["balance"] + data["bank"]
        embed = discord.Embed(title=f"{CURRENCY} {target.display_name}'s Wallet", color=0xffaa3d)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name=f"{CURRENCY} Wallet",   value=f"`{data['balance']:,}`",     inline=True)
        embed.add_field(name="🏦 Bank",              value=f"`{data['bank']:,}`",        inline=True)
        embed.add_field(name="💎 Total Earned",      value=f"`{data['total_earned']:,}`",inline=True)
        embed.add_field(name="🏆 Server Rank",       value=f"`#{rank}`",                 inline=True)
        embed.set_footer(text=f"Net worth: {net:,} {CURRENCY}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="See the richest members in the server.")
    async def leaderboard(self, interaction: discord.Interaction):
        board = await db.get_leaderboard(interaction.guild_id, 10)
        if not board:
            await interaction.response.send_message(
                embed=discord.Embed(description="No economy data yet.", color=0xED4245), ephemeral=True)
            return
        medals = ["🥇","🥈","🥉"]
        embed  = discord.Embed(title=f"💰 {interaction.guild.name} — Rich List", color=0xffaa3d)
        lines  = []
        for i, row in enumerate(board):
            m    = interaction.guild.get_member(row["user_id"])
            name = m.display_name if m else f"User {row['user_id']}"
            net  = row["balance"] + row["bank"]
            medal = medals[i] if i < 3 else f"`#{i+1}`"
            lines.append(f"{medal} **{name}** — `{net:,}` {CURRENCY}")
        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="inventory", description="View your item inventory.")
    async def inventory(self, interaction: discord.Interaction):
        items = await db.get_inventory(interaction.guild_id, interaction.user.id)
        embed = discord.Embed(title=f"🎒 {interaction.user.display_name}'s Inventory", color=0x3d8bff)
        if not items:
            embed.description = "Your inventory is empty. Check out `/shop`!"
        else:
            embed.description = "\n".join(
                f"{i['emoji']} **{i['name']}** ×{i['quantity']} — {i['description'] or 'No description'}"
                for i in items)
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot): await bot.add_cog(Balance(bot))
