import discord
from discord import app_commands
from discord.ext import commands

class Avatar(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="avatar", description="Get a user's avatar in full size.")
    @app_commands.describe(user="User to get avatar for (default: yourself)")
    async def avatar(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        embed = discord.Embed(title=f"🖼️ {target.display_name}'s Avatar", color=0x5865F2)
        embed.set_image(url=target.display_avatar.url)
        embed.add_field(name="Links", value=(
            f"[PNG]({target.display_avatar.with_format('png').url})  •  "
            f"[JPG]({target.display_avatar.with_format('jpg').url})  •  "
            f"[WEBP]({target.display_avatar.with_format('webp').url})"
        ))
        embed.set_footer(text=f"ID: {target.id}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="banner", description="Get a user's profile banner.")
    @app_commands.describe(user="User to get banner for (default: yourself)")
    async def banner(self, interaction: discord.Interaction, user: discord.Member = None):
        target  = user or interaction.user
        fetched = await self.bot.fetch_user(target.id)
        if not fetched.banner:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"{target.mention} has no banner.", color=0xED4245),
                ephemeral=True)
            return
        embed = discord.Embed(title=f"🎨 {target.display_name}'s Banner",
                               color=fetched.accent_color or 0x5865F2)
        embed.set_image(url=fetched.banner.url)
        await interaction.response.send_message(embed=embed)

async def setup(bot): await bot.add_cog(Avatar(bot))
