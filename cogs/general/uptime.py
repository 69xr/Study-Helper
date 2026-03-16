import discord, time
from discord import app_commands
from discord.ext import commands
from utils import db

START_TIME = time.time()

class Uptime(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="uptime", description="How long the bot has been online.")
    async def uptime(self, interaction: discord.Interaction):
        e = int(time.time() - START_TIME)
        d, r = divmod(e, 86400); h, r = divmod(r, 3600); m, s = divmod(r, 60)
        total_cmds = await db.get_total_commands()
        embed = discord.Embed(title="⏱️ Uptime", color=0x5DADE2)
        embed.add_field(name="Online For",    value=f"`{d}d {h}h {m}m {s}s`",           inline=False)
        embed.add_field(name="Commands Used", value=f"`{total_cmds:,}`",                 inline=True)
        embed.add_field(name="Guilds",        value=f"`{len(self.bot.guilds)}`",          inline=True)
        embed.add_field(name="Latency",       value=f"`{round(self.bot.latency*1000)} ms`", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="botinfo", description="Detailed information about this bot.")
    async def botinfo(self, interaction: discord.Interaction):
        total_users = sum(g.member_count for g in self.bot.guilds)
        total_cmds  = await db.get_total_commands()
        top_cmds    = await db.get_top_commands(5)
        e = int(time.time() - START_TIME)
        d, r = divmod(e, 86400); h, r = divmod(r, 3600); m, _ = divmod(r, 60)
        embed = discord.Embed(title="🤖 Bot Information", color=0x5865F2)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.add_field(name="Bot",     value=f"`{self.bot.user}`",        inline=True)
        embed.add_field(name="ID",      value=f"`{self.bot.user.id}`",     inline=True)
        embed.add_field(name="Library", value="`discord.py v2`",           inline=True)
        embed.add_field(name="Guilds",  value=f"`{len(self.bot.guilds)}`", inline=True)
        embed.add_field(name="Users",   value=f"`{total_users:,}`",        inline=True)
        embed.add_field(name="Uptime",  value=f"`{d}d {h}h {m}m`",        inline=True)
        embed.add_field(name="Commands",value=f"`{total_cmds:,}` total",   inline=True)
        embed.add_field(name="Latency", value=f"`{round(self.bot.latency*1000)} ms`", inline=True)
        if top_cmds:
            embed.add_field(name="🏆 Top Commands",
                value="\n".join(f"`/{c['command']}` — {c['uses']} uses" for c in top_cmds), inline=False)
        embed.set_footer(text=f"Requested by {interaction.user}", icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

async def setup(bot): await bot.add_cog(Uptime(bot))
