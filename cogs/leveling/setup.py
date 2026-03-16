import discord, aiosqlite
from discord import app_commands
from discord.ext import commands
from utils import db
from utils.helpers import success_embed, error_embed
import config

class LevelSetup(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="levelsetup", description="Configure the leveling system.")
    @app_commands.describe(enabled="Enable/disable leveling", xp_min="Min XP per message",
                           xp_max="Max XP per message", cooldown="Cooldown between XP gains (seconds)",
                           level_up_channel="Channel for announcements", level_up_msg="Level-up message template")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def levelsetup(self, interaction: discord.Interaction,
                          enabled: bool = None, xp_min: app_commands.Range[int,1,500] = None,
                          xp_max: app_commands.Range[int,1,500] = None,
                          cooldown: app_commands.Range[int,5,3600] = None,
                          level_up_channel: discord.TextChannel = None, level_up_msg: str = None):
        if enabled is not None:  await db.set_level_setting(interaction.guild_id, "enabled", int(enabled))
        if xp_min is not None:   await db.set_level_setting(interaction.guild_id, "xp_min", xp_min)
        if xp_max is not None:   await db.set_level_setting(interaction.guild_id, "xp_max", xp_max)
        if cooldown is not None: await db.set_level_setting(interaction.guild_id, "xp_cooldown", cooldown)
        if level_up_channel:     await db.set_level_setting(interaction.guild_id, "level_up_channel", level_up_channel.id)
        if level_up_msg:         await db.set_level_setting(interaction.guild_id, "level_up_msg", level_up_msg)
        s   = await db.get_level_settings(interaction.guild_id)
        lch = interaction.guild.get_channel(s["level_up_channel"]) if s.get("level_up_channel") else None
        embed = success_embed("Leveling Configured")
        embed.add_field(name="Status",   value="✅ Enabled" if s["enabled"] else "❌ Disabled",     inline=True)
        embed.add_field(name="XP Range", value=f"`{s['xp_min']}–{s['xp_max']}` per msg",           inline=True)
        embed.add_field(name="Cooldown", value=f"`{s['xp_cooldown']}s`",                            inline=True)
        embed.add_field(name="Channel",  value=lch.mention if lch else "Same channel",              inline=True)
        embed.add_field(name="Message",  value=f"`{s['level_up_msg']}`",                            inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="setlevelrole", description="Set a role reward for reaching a level.")
    @app_commands.describe(level="Level to unlock the role", role="Role to give")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def setlevelrole(self, interaction: discord.Interaction,
                            level: app_commands.Range[int,1,500], role: discord.Role):
        await db.set_level_role(interaction.guild_id, level, role.id)
        await interaction.response.send_message(
            embed=success_embed("Level Role Set", f"{role.mention} unlocked at Level **{level}**."), ephemeral=True)

    @app_commands.command(name="removelevelrole", description="Remove a level role reward.")
    @app_commands.describe(level="Level to remove the role from")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def removelevelrole(self, interaction: discord.Interaction, level: int):
        await db.remove_level_role(interaction.guild_id, level)
        await interaction.response.send_message(
            embed=success_embed("Removed", f"Level role for Level **{level}** removed."), ephemeral=True)

    @app_commands.command(name="resetxp", description="[Admin] Reset a user's XP and level.")
    @app_commands.describe(user="User to reset")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def resetxp(self, interaction: discord.Interaction, user: discord.Member):
        async with aiosqlite.connect(config.DB_PATH) as db_conn:
            await db_conn.execute(
                "UPDATE levels SET xp=0,level=0,messages=0,last_xp=NULL WHERE guild_id=? AND user_id=?",
                (interaction.guild_id, user.id))
            await db_conn.commit()
        await interaction.response.send_message(
            embed=success_embed("Reset", f"{user.mention}'s XP has been reset to 0."), ephemeral=True)

    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=error_embed("Missing Permissions"), ephemeral=True)

async def setup(bot): await bot.add_cog(LevelSetup(bot))
