import discord
from discord import app_commands
from discord.ext import commands
from utils import db
from utils.helpers import success_embed, error_embed

class Config(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="setlog", description="Set the moderation log channel.")
    @app_commands.describe(channel="Channel for mod logs (leave empty to disable)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setlog(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        await db.set_guild_setting(interaction.guild_id, "log_channel", channel.id if channel else None)
        if channel:
            await interaction.response.send_message(
                embed=success_embed("Log Channel Set", f"Mod logs → {channel.mention}."), ephemeral=True)
        else:
            await interaction.response.send_message(
                embed=success_embed("Log Disabled", "Mod logging turned off."), ephemeral=True)

    @app_commands.command(name="setwelcome", description="Set the welcome channel and message.")
    @app_commands.describe(channel="Welcome channel", message="Template: {user} {server} {count}")
    @app_commands.checks.has_permissions(administrator=True)
    async def setwelcome(self, interaction: discord.Interaction, channel: discord.TextChannel,
                          message: str = "Welcome {user} to **{server}**! You are member #{count}."):
        await db.set_guild_setting(interaction.guild_id, "welcome_channel", channel.id)
        await db.set_guild_setting(interaction.guild_id, "welcome_msg", message)
        preview = message.replace("{user}", interaction.user.mention) \
                         .replace("{server}", interaction.guild.name) \
                         .replace("{count}", str(interaction.guild.member_count))
        embed = success_embed("Welcome Set", f"Welcome messages → {channel.mention}")
        embed.add_field(name="Preview", value=preview, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="settings", description="View all current bot settings.")
    @app_commands.checks.has_permissions(administrator=True)
    async def settings_cmd(self, interaction: discord.Interaction):
        s  = await db.get_guild_settings(interaction.guild_id)
        ts = await db.get_ticket_settings(interaction.guild_id)
        log_ch     = interaction.guild.get_channel(s["log_channel"])     if s and s.get("log_channel")     else None
        welcome_ch = interaction.guild.get_channel(s["welcome_channel"]) if s and s.get("welcome_channel") else None
        mute_role  = interaction.guild.get_role(s["mute_role"])          if s and s.get("mute_role")       else None
        embed = discord.Embed(title=f"⚙️ Settings — {interaction.guild.name}", color=0x5865F2)
        embed.add_field(name="📋 Log Channel",     value=log_ch.mention     if log_ch     else "`not set`", inline=True)
        embed.add_field(name="👋 Welcome Channel", value=welcome_ch.mention if welcome_ch else "`not set`", inline=True)
        embed.add_field(name="🔇 Mute Role",       value=mute_role.mention  if mute_role  else "`not set`", inline=True)
        embed.add_field(name="💬 Welcome Msg",     value=f"`{s.get('welcome_msg','not set')}`" if s else "`not set`", inline=False)
        embed.add_field(name="🎫 Ticket Category", value=f"`{ts.get('category_id','—')}`",  inline=True)
        embed.add_field(name="🛡 Support Role",    value=f"`{ts.get('support_role','—')}`",  inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        s = await db.get_guild_settings(member.guild.id)
        if not s or not s.get("welcome_channel"): return
        ch = member.guild.get_channel(s["welcome_channel"])
        if not ch: return
        msg = (s.get("welcome_msg") or "Welcome {user} to **{server}**!") \
              .replace("{user}", member.mention) \
              .replace("{server}", member.guild.name) \
              .replace("{count}", str(member.guild.member_count))
        embed = discord.Embed(title="👋 Welcome!", description=msg, color=0x57F287)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Member #{member.guild.member_count}")
        try: await ch.send(embed=embed)
        except discord.Forbidden: pass

    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=error_embed("Missing Permissions"), ephemeral=True)

async def setup(bot): await bot.add_cog(Config(bot))
