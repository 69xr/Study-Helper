"""
cogs/moderation.py
Commands: /kick  /ban  /unban  /clear  /warn  /warnings  /clearwarns  /delwarn
"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
from utils import db
from utils.helpers import mod_embed, error_embed, success_embed, warning_embed, send_log
import config


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Internal: get log channel ─────────────────────────────
    async def _log_channel(self, guild_id: int) -> int | None:
        settings = await db.get_guild_settings(guild_id)
        return settings["log_channel"] if settings else None

    # ── /kick ─────────────────────────────────────────────────
    @app_commands.command(name="kick", description="Kick a member from the server.")
    @app_commands.describe(member="Member to kick", reason="Reason")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                embed=error_embed("Can't Kick", "That member's role is too high for me to kick."), ephemeral=True
            )
            return
        if member == interaction.user:
            await interaction.response.send_message(embed=error_embed("Can't Kick", "You can't kick yourself."), ephemeral=True)
            return

        try:
            await member.send(
                embed=warning_embed(
                    f"Kicked from {interaction.guild.name}",
                    f"**Reason:** {reason}"
                )
            )
        except discord.Forbidden:
            pass

        await member.kick(reason=f"{interaction.user}: {reason}")
        await db.log_action(interaction.guild_id, "KICK", interaction.user.id, member.id, reason)

        embed = mod_embed("👢  Member Kicked", member, interaction.user, reason, 0xFEE75C)
        await interaction.response.send_message(embed=embed)

        log_ch = await self._log_channel(interaction.guild_id)
        await send_log(interaction.guild, log_ch, embed)

    # ── /ban ──────────────────────────────────────────────────
    @app_commands.command(name="ban", description="Ban a member from the server.")
    @app_commands.describe(member="Member to ban", reason="Reason", delete_days="Days of messages to delete (0-7)")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided", delete_days: app_commands.Range[int, 0, 7] = 0):
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                embed=error_embed("Can't Ban", "That member's role is too high for me to ban."), ephemeral=True
            )
            return

        try:
            await member.send(
                embed=error_embed(
                    f"Banned from {interaction.guild.name}",
                    f"**Reason:** {reason}"
                )
            )
        except discord.Forbidden:
            pass

        await member.ban(reason=f"{interaction.user}: {reason}", delete_message_days=delete_days)
        await db.log_action(interaction.guild_id, "BAN", interaction.user.id, member.id, reason)

        embed = mod_embed("🔨  Member Banned", member, interaction.user, reason, 0xED4245)
        await interaction.response.send_message(embed=embed)

        log_ch = await self._log_channel(interaction.guild_id)
        await send_log(interaction.guild, log_ch, embed)

    # ── /unban ────────────────────────────────────────────────
    @app_commands.command(name="unban", description="Unban a user by ID.")
    @app_commands.describe(user_id="The user's ID", reason="Reason")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
        try:
            uid = int(user_id)
        except ValueError:
            await interaction.response.send_message(embed=error_embed("Invalid ID", "That's not a valid user ID."), ephemeral=True)
            return

        try:
            user = await self.bot.fetch_user(uid)
            await interaction.guild.unban(user, reason=f"{interaction.user}: {reason}")
        except discord.NotFound:
            await interaction.response.send_message(embed=error_embed("Not Banned", "That user is not banned."), ephemeral=True)
            return

        embed = discord.Embed(title="✅  User Unbanned", color=0x57F287)
        embed.add_field(name="User",   value=f"`{user}` (`{user.id}`)", inline=True)
        embed.add_field(name="Mod",    value=interaction.user.mention,  inline=True)
        embed.add_field(name="Reason", value=reason,                    inline=False)
        await interaction.response.send_message(embed=embed)

    # ── /clear ────────────────────────────────────────────────
    @app_commands.command(name="clear", description="Delete messages from this channel.")
    @app_commands.describe(amount="Number of messages (1-100)", user="Only delete messages from this user")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, 100] = 10,
        user: discord.Member = None
    ):
        await interaction.response.defer(ephemeral=True)

        def check(msg):
            return user is None or msg.author == user

        deleted = await interaction.channel.purge(limit=amount, check=check)
        await interaction.followup.send(
            embed=success_embed("Messages Cleared", f"Deleted `{len(deleted)}` message(s)."),
            ephemeral=True
        )

    # ── /warn ─────────────────────────────────────────────────
    @app_commands.command(name="warn", description="Warn a member.")
    @app_commands.describe(member="Member to warn", reason="Reason for warning")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        if member.bot:
            await interaction.response.send_message(embed=error_embed("Can't Warn", "You can't warn a bot."), ephemeral=True)
            return

        total = await db.add_warning(interaction.guild_id, member.id, interaction.user.id, reason)
        await db.log_action(interaction.guild_id, "WARN", interaction.user.id, member.id, reason, str(total))

        embed = discord.Embed(title="⚠️  Warning Issued", color=0xFEE75C, timestamp=datetime.now(timezone.utc))
        embed.add_field(name="👤 User",      value=f"{member.mention}\n`{member}`", inline=True)
        embed.add_field(name="🛡️ Mod",      value=interaction.user.mention,        inline=True)
        embed.add_field(name="📋 Reason",    value=reason,                          inline=False)
        embed.add_field(name="⚠️ Total Warns", value=f"`{total}`",                 inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"User ID: {member.id}")

        await interaction.response.send_message(embed=embed)

        # DM the warned user
        try:
            dm_embed = discord.Embed(
                title=f"⚠️ You received a warning in {interaction.guild.name}",
                description=f"**Reason:** {reason}\n**Total warnings:** {total}",
                color=0xFEE75C
            )
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass

        # Log
        log_ch = await self._log_channel(interaction.guild_id)
        await send_log(interaction.guild, log_ch, embed)

        # Auto-kick after threshold
        if total >= config.MAX_WARNS_BEFORE_KICK:
            kicked = False
            try:
                await member.kick(reason=f"Auto-kick: reached {total} warnings")
                kicked = True
            except discord.Forbidden:
                pass
            if kicked:
                try:
                    await interaction.followup.send(
                        embed=warning_embed(
                            "Auto-Kick Triggered",
                            f"{member.mention} was auto-kicked after reaching **{total}** warnings."
                        )
                    )
                except Exception:
                    pass

    # ── /warnings ─────────────────────────────────────────────
    @app_commands.command(name="warnings", description="View a member's warnings.")
    @app_commands.describe(member="Member to check")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        warns = await db.get_warnings(interaction.guild_id, member.id)

        if not warns:
            await interaction.response.send_message(
                embed=success_embed("No Warnings", f"{member.mention} has no warnings."),
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"⚠️  Warnings — {member}",
            color=0xFEE75C
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        for w in warns[:10]:   # show up to 10
            mod = interaction.guild.get_member(w["mod_id"])
            mod_str = str(mod) if mod else f"ID: {w['mod_id']}"
            embed.add_field(
                name=f"#{w['id']} — {w['created_at'][:10]}",
                value=f"**Reason:** {w['reason']}\n**Mod:** {mod_str}",
                inline=False
            )

        embed.set_footer(text=f"Total: {len(warns)} warning(s)")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /clearwarns ───────────────────────────────────────────
    @app_commands.command(name="clearwarns", description="Clear all warnings for a member.")
    @app_commands.describe(member="Member whose warnings to clear")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clearwarns(self, interaction: discord.Interaction, member: discord.Member):
        count = await db.clear_warnings(interaction.guild_id, member.id)
        if count == 0:
            await interaction.response.send_message(
                embed=error_embed("No Warnings", f"{member.mention} had no warnings to clear."),
                ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=success_embed("Warnings Cleared", f"Cleared **{count}** warning(s) for {member.mention}."),
            ephemeral=True
        )

    # ── /delwarn ──────────────────────────────────────────────
    @app_commands.command(name="delwarn", description="Delete a specific warning by its ID.")
    @app_commands.describe(warning_id="The warning ID (from /warnings)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def delwarn(self, interaction: discord.Interaction, warning_id: int):
        removed = await db.remove_warning(warning_id, interaction.guild_id)
        if not removed:
            await interaction.response.send_message(
                embed=error_embed("Not Found", f"No warning with ID `{warning_id}` found in this server."),
                ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=success_embed("Warning Removed", f"Warning `#{warning_id}` has been deleted."),
            ephemeral=True
        )

    # ── Global error handler ──────────────────────────────────
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=error_embed("Missing Permissions", "You don't have permission to use this command."),
                    ephemeral=True
                )


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
