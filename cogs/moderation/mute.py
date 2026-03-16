import discord, asyncio, re
from discord import app_commands
from discord.ext import commands
from utils import db
from utils.helpers import success_embed, error_embed, send_log
import config

def parse_duration(s: str) -> int | None:
    total = 0
    for num, unit in re.findall(r"(\d+)([smhd])", s.lower()):
        n = int(num)
        if unit == "s": total += n
        elif unit == "m": total += n * 60
        elif unit == "h": total += n * 3600
        elif unit == "d": total += n * 86400
    return total if total > 0 else None

class Mute(commands.Cog):
    def __init__(self, bot): self.bot = bot

    async def _get_mute_role(self, guild: discord.Guild) -> discord.Role | None:
        s = await db.get_guild_settings(guild.id)
        if s and s.get("mute_role"):
            return guild.get_role(s["mute_role"])
        return None

    @app_commands.command(name="mute", description="Mute a member so they can't send messages.")
    @app_commands.describe(member="Member to mute", duration="Duration e.g. 10m 1h 1d (leave empty = permanent)", reason="Reason")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def mute(self, interaction: discord.Interaction,
                   member: discord.Member,
                   duration: str = None,
                   reason: str = "No reason provided"):
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message(embed=error_embed("Can't Mute", "That member's role is too high."), ephemeral=True)
            return
        if member == interaction.user:
            await interaction.response.send_message(embed=error_embed("Can't Mute", "You can't mute yourself."), ephemeral=True)
            return

        mute_role = await self._get_mute_role(interaction.guild)
        if not mute_role:
            await interaction.response.send_message(
                embed=error_embed("No Mute Role", "Set a mute role in `/settings` or the dashboard first."),
                ephemeral=True)
            return

        secs = parse_duration(duration) if duration else None
        dur_str = duration if secs else "Permanent"

        try:
            await member.add_roles(mute_role, reason=f"{interaction.user}: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message(embed=error_embed("Missing Permissions"), ephemeral=True)
            return

        await db.log_action(interaction.guild_id, "MUTE", interaction.user.id, member.id, reason, dur_str)

        embed = success_embed(f"🔇 Muted {member.display_name}")
        embed.add_field(name="Duration", value=f"`{dur_str}`", inline=True)
        embed.add_field(name="Reason",   value=reason,          inline=True)
        await interaction.response.send_message(embed=embed)

        try:
            await member.send(embed=discord.Embed(
                title=f"🔇 You were muted in {interaction.guild.name}",
                description=f"**Duration:** {dur_str}\n**Reason:** {reason}",
                color=0xED4245))
        except: pass

        s = await db.get_guild_settings(interaction.guild_id)
        if s and s.get("log_channel"):
            await send_log(interaction.guild, s["log_channel"], embed)

        if secs:
            async def auto_unmute():
                await asyncio.sleep(secs)
                try:
                    await member.remove_roles(mute_role, reason="Auto-unmute: duration expired")
                    ch = interaction.channel
                    if ch:
                        await ch.send(embed=discord.Embed(
                            description=f"🔊 {member.mention} has been automatically unmuted.",
                            color=0x57F287), delete_after=10)
                except: pass
            self.bot.loop.create_task(auto_unmute())

    @app_commands.command(name="unmute", description="Unmute a muted member.")
    @app_commands.describe(member="Member to unmute", reason="Reason")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def unmute(self, interaction: discord.Interaction,
                     member: discord.Member, reason: str = "No reason provided"):
        mute_role = await self._get_mute_role(interaction.guild)
        if not mute_role:
            await interaction.response.send_message(embed=error_embed("No Mute Role", "Set a mute role first."), ephemeral=True)
            return
        if mute_role not in member.roles:
            await interaction.response.send_message(embed=error_embed("Not Muted", f"{member.mention} is not muted."), ephemeral=True)
            return
        await member.remove_roles(mute_role, reason=f"{interaction.user}: {reason}")
        await db.log_action(interaction.guild_id, "UNMUTE", interaction.user.id, member.id, reason)
        embed = success_embed(f"🔊 Unmuted {member.display_name}", reason)
        await interaction.response.send_message(embed=embed)
        s = await db.get_guild_settings(interaction.guild_id)
        if s and s.get("log_channel"):
            await send_log(interaction.guild, s["log_channel"], embed)

    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=error_embed("Missing Permissions"), ephemeral=True)

async def setup(bot): await bot.add_cog(Mute(bot))
