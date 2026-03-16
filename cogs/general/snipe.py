import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone

# In-memory snipe cache: channel_id -> {content, author, deleted_at, attachment}
_snipe_cache: dict[int, dict] = {}

class Snipe(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild: return
        attachment_url = message.attachments[0].url if message.attachments else None
        _snipe_cache[message.channel.id] = {
            "content":      message.content or "*[no text content]*",
            "author_name":  str(message.author),
            "author_avatar":message.author.display_avatar.url,
            "author_id":    message.author.id,
            "deleted_at":   datetime.now(timezone.utc),
            "attachment":   attachment_url,
        }

    @app_commands.command(name="snipe", description="Show the last deleted message in this channel.")
    async def snipe(self, interaction: discord.Interaction):
        data = _snipe_cache.get(interaction.channel_id)
        if not data:
            await interaction.response.send_message(
                embed=discord.Embed(description="Nothing to snipe here! No recently deleted messages.", color=0xED4245),
                ephemeral=True)
            return
        ts = int(data["deleted_at"].timestamp())
        embed = discord.Embed(description=data["content"], color=0xFEE75C, timestamp=data["deleted_at"])
        embed.set_author(name=data["author_name"], icon_url=data["author_avatar"])
        embed.set_footer(text=f"Deleted at")
        if data["attachment"]:
            embed.set_image(url=data["attachment"])
        await interaction.response.send_message(embed=embed)

async def setup(bot): await bot.add_cog(Snipe(bot))
