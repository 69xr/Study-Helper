"""
cogs/settings/config.py
All server configuration is now managed exclusively via the Dashboard.
This cog retains only the on_member_join welcome listener.
"""
import discord
from discord.ext import commands
from utils import db


class Config(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Send welcome embed when a member joins."""
        s = await db.get_guild_settings(member.guild.id)
        if not s or not s.get("welcome_channel"):
            return
        ch = member.guild.get_channel(s["welcome_channel"])
        if not ch:
            return
        msg = (s.get("welcome_msg") or "Welcome {user} to **{server}**!") \
              .replace("{user}", member.mention) \
              .replace("{server}", member.guild.name) \
              .replace("{count}", str(member.guild.member_count))
        embed = discord.Embed(
            title="👋 Welcome!",
            description=msg,
            color=0x57F287,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Member #{member.guild.member_count}")
        try:
            await ch.send(embed=embed)
        except discord.Forbidden:
            pass


async def setup(bot):
    await bot.add_cog(Config(bot))
