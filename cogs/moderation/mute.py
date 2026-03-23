"""
cogs/moderation/mute.py
/mute /unmute
Auto-creates the Muted role if missing and configures every channel.
"""
import discord, asyncio, re
from discord import app_commands
from discord.ext import commands
from utils import db
from utils.helpers import success_embed, error_embed, mod_embed, send_log
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


async def setup_mute_role(guild: discord.Guild) -> discord.Role | None:
    """
    Get or create the Muted role and apply deny permissions to every channel.
    This is the KEY feature — no manual setup needed.
    """
    s = await db.get_guild_settings(guild.id)
    mute_role = guild.get_role(s["mute_role"]) if s and s.get("mute_role") else None

    if not mute_role:
        # Create the role
        try:
            mute_role = await guild.create_role(
                name=config.MUTE_ROLE_NAME,
                color=discord.Color.dark_grey(),
                reason="Severus auto-created mute role"
            )
            await db.set_guild_setting(guild.id, "mute_role", mute_role.id)
        except discord.Forbidden:
            return None

    # Apply to ALL channels — deny send/speak/react
    deny = discord.PermissionOverwrite(
        send_messages=False,
        speak=False,
        add_reactions=False,
        send_messages_in_threads=False,
        create_public_threads=False,
        create_private_threads=False,
    )
    failed = 0
    for channel in guild.channels:
        try:
            await channel.set_permissions(mute_role, overwrite=deny,
                                          reason="Severus mute role setup")
        except (discord.Forbidden, discord.HTTPException):
            failed += 1

    return mute_role


class Mute(commands.Cog):
    def __init__(self, bot): 
        self.bot = bot
        self._unmute_tasks: set[asyncio.Task] = set()  # prevent GC of running tasks

    @app_commands.command(name="mute", description="Mute a member (auto-creates mute role if needed).")
    @app_commands.describe(
        member="Member to mute",
        duration="Duration: 10m 1h 2d (leave empty = permanent)",
        reason="Reason for mute"
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def mute(self, interaction: discord.Interaction,
                   member: discord.Member,
                   duration: str = None,
                   reason: str = "No reason provided"):
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                embed=error_embed("Can't Mute", "That member's role is too high."), ephemeral=True)
            return
        if member == interaction.user:
            await interaction.response.send_message(
                embed=error_embed("Can't Mute", "You can't mute yourself."), ephemeral=True)
            return
        if member.guild_permissions.administrator:
            await interaction.response.send_message(
                embed=error_embed("Can't Mute", "You can't mute an administrator."), ephemeral=True)
            return

        await interaction.response.defer()

        # Auto-setup mute role — creates it and configures every channel if needed
        mute_role = await setup_mute_role(interaction.guild)
        if not mute_role:
            await interaction.followup.send(
                embed=error_embed("No Permission",
                    "I don't have permission to create or manage roles.\n"
                    "Give me **Manage Roles** permission and try again."))
            return

        if mute_role in member.roles:
            await interaction.followup.send(
                embed=error_embed("Already Muted", f"{member.mention} is already muted."))
            return

        secs    = parse_duration(duration) if duration else None
        dur_str = duration if secs else "Permanent"

        await member.add_roles(mute_role, reason=f"Muted by {interaction.user}: {reason}")
        await db.log_action(interaction.guild_id, "MUTE", interaction.user.id, member.id, reason, dur_str)

        embed = mod_embed(f"🔇 Member Muted", member, interaction.user, reason, config.Colors.WARN)
        embed.add_field(name="⏱️ Duration", value=f"`{dur_str}`", inline=True)
        await interaction.followup.send(embed=embed)

        # DM the muted member
        try:
            dm = discord.Embed(
                title=f"🔇 You were muted in **{interaction.guild.name}**",
                description=f"**Duration:** `{dur_str}`\n**Reason:** {reason}",
                color=config.Colors.WARN)
            await member.send(embed=dm)
        except Exception:
            pass

        # Send to log channel
        s = await db.get_guild_settings(interaction.guild_id)
        if s and s.get("log_channel"):
            await send_log(interaction.guild, s["log_channel"], embed)

        # Auto-unmute after duration
        if secs:
            async def auto_unmute():
                await asyncio.sleep(secs)
                try:
                    if mute_role in member.roles:
                        await member.remove_roles(mute_role, reason="Auto-unmute: duration expired")
                        ch = interaction.channel
                        if ch:
                            await ch.send(
                                embed=success_embed("Auto-Unmuted",
                                    f"{member.mention} has been automatically unmuted."),
                                delete_after=10)
                except Exception:
                    pass
            task = asyncio.create_task(auto_unmute())
            self._unmute_tasks.add(task)
            task.add_done_callback(self._unmute_tasks.discard)

    @app_commands.command(name="unmute", description="Unmute a muted member.")
    @app_commands.describe(member="Member to unmute", reason="Reason")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def unmute(self, interaction: discord.Interaction,
                     member: discord.Member,
                     reason: str = "No reason provided"):
        s = await db.get_guild_settings(interaction.guild_id)
        mute_role = interaction.guild.get_role(s["mute_role"]) if s and s.get("mute_role") else None

        if not mute_role or mute_role not in member.roles:
            await interaction.response.send_message(
                embed=error_embed("Not Muted", f"{member.mention} is not muted."), ephemeral=True)
            return

        await member.remove_roles(mute_role, reason=f"Unmuted by {interaction.user}: {reason}")
        await db.log_action(interaction.guild_id, "UNMUTE", interaction.user.id, member.id, reason)

        embed = success_embed("🔊 Member Unmuted", f"{member.mention} has been unmuted.")
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="Reason",    value=reason,                   inline=True)
        await interaction.response.send_message(embed=embed)

        s2 = await db.get_guild_settings(interaction.guild_id)
        if s2 and s2.get("log_channel"):
            await send_log(interaction.guild, s2["log_channel"], embed)

    @app_commands.command(name="setupmute",
                          description="Create/fix the Muted role and apply it to all channels.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setupmute(self, interaction: discord.Interaction):
        await interaction.response.defer()
        mute_role = await setup_mute_role(interaction.guild)
        if not mute_role:
            await interaction.followup.send(
                embed=error_embed("Failed", "I need **Manage Roles** and **Manage Channels** permissions."))
            return
        ch_count = len(interaction.guild.channels)
        embed = success_embed("✅ Mute Role Ready",
            f"The **{mute_role.mention}** role has been configured.\n"
            f"Applied deny overrides to **{ch_count}** channels.\n"
            f"Members with this role cannot send messages or speak anywhere.")
        await interaction.followup.send(embed=embed)

    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=error_embed("Missing Permissions", "You need **Manage Messages** for this."),
                    ephemeral=True)


async def setup(bot): await bot.add_cog(Mute(bot))
