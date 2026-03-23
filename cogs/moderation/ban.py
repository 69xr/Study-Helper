"""
cogs/moderation/ban.py  — v20
Improvements:
  • Deferred response to prevent timeout on slow guilds
  • /softban  — ban + unban to delete messages without keeping ban
  • /massban  — ban multiple user IDs (owner/admin only)
  • Better role hierarchy check (checks interaction user too)
  • Audit log for unban
"""
import discord
from discord import app_commands
from discord.ext import commands
from utils import db
from utils.helpers import mod_embed, error_embed, success_embed, send_log
import asyncio


class Ban(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── /ban ──────────────────────────────────────────────────
    @app_commands.command(name="ban", description="Ban a member from the server.")
    @app_commands.describe(member="Member to ban", reason="Reason for the ban", delete_days="Days of messages to delete (0–7)")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction,
                  member: discord.Member, reason: str = "No reason provided",
                  delete_days: app_commands.Range[int, 0, 7] = 0):
        await interaction.response.defer()

        # Hierarchy checks
        if member == interaction.user:
            await interaction.followup.send(embed=error_embed("Can't Ban", "You can't ban yourself."), ephemeral=True)
            return
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.followup.send(
                embed=error_embed("Can't Ban", "That member's role is too high for me to ban."), ephemeral=True)
            return
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            await interaction.followup.send(
                embed=error_embed("Can't Ban", "You can't ban someone with an equal or higher role."), ephemeral=True)
            return

        # DM before ban (they'll lose access after)
        dm_sent = False
        try:
            await member.send(embed=discord.Embed(
                title=f"🔨 Banned from {interaction.guild.name}",
                description=f"**Reason:** {reason}\n\nYou may appeal if this server has an appeal process.",
                color=0xED4245))
            dm_sent = True
        except discord.Forbidden:
            pass

        await member.ban(reason=f"{interaction.user}: {reason}", delete_message_days=delete_days)
        await db.log_action(interaction.guild_id, "BAN", interaction.user.id, member.id, reason)

        embed = mod_embed("🔨  Member Banned", member, interaction.user, reason, 0xED4245)
        if not dm_sent:
            embed.set_footer(text="⚠ DMs blocked — member not notified")
        await interaction.followup.send(embed=embed)

        s = await db.get_guild_settings(interaction.guild_id)
        if s and s.get("log_channel"):
            await send_log(interaction.guild, s["log_channel"], embed)

    # ── /softban ──────────────────────────────────────────────
    @app_commands.command(name="softban", description="Ban then immediately unban to delete messages without keeping the ban.")
    @app_commands.describe(member="Member to softban", reason="Reason", delete_days="Days of messages to delete (1–7)")
    @app_commands.checks.has_permissions(ban_members=True)
    async def softban(self, interaction: discord.Interaction,
                      member: discord.Member, reason: str = "No reason provided",
                      delete_days: app_commands.Range[int, 1, 7] = 1):
        await interaction.response.defer()

        if member.top_role >= interaction.guild.me.top_role:
            await interaction.followup.send(embed=error_embed("Can't Softban", "That member's role is too high."), ephemeral=True)
            return

        try:
            await member.send(embed=discord.Embed(
                title=f"🔨 Kicked from {interaction.guild.name}",
                description=f"**Reason:** {reason}",
                color=0xFEE75C))
        except discord.Forbidden:
            pass

        await member.ban(reason=f"Softban by {interaction.user}: {reason}", delete_message_days=delete_days)
        await asyncio.sleep(0.5)
        await interaction.guild.unban(member, reason="Softban — auto-unban")
        await db.log_action(interaction.guild_id, "SOFTBAN", interaction.user.id, member.id, reason)

        embed = mod_embed("🔨  Member Softbanned", member, interaction.user, reason, 0xFEE75C)
        embed.add_field(name="ℹ️ Info", value=f"Banned then unbanned — last {delete_days} day(s) of messages deleted.", inline=False)
        await interaction.followup.send(embed=embed)

    # ── /unban ────────────────────────────────────────────────
    @app_commands.command(name="unban", description="Unban a user by their Discord ID.")
    @app_commands.describe(user_id="The user's Discord ID", reason="Reason for unban")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction,
                    user_id: str, reason: str = "No reason provided"):
        await interaction.response.defer()

        try:
            uid = int(user_id.strip())
        except ValueError:
            await interaction.followup.send(embed=error_embed("Invalid ID", "That doesn't look like a valid Discord user ID."), ephemeral=True)
            return

        try:
            user = await self.bot.fetch_user(uid)
            await interaction.guild.unban(user, reason=f"{interaction.user}: {reason}")
        except discord.NotFound:
            await interaction.followup.send(embed=error_embed("Not Banned", "That user is not in the ban list."), ephemeral=True)
            return
        except discord.Forbidden:
            await interaction.followup.send(embed=error_embed("No Permission", "I don't have permission to unban members."), ephemeral=True)
            return

        embed = discord.Embed(title="✅  User Unbanned", color=0x57F287)
        embed.add_field(name="User",   value=f"`{user}` (`{user.id}`)", inline=True)
        embed.add_field(name="Mod",    value=interaction.user.mention,  inline=True)
        embed.add_field(name="Reason", value=reason,                    inline=False)
        await interaction.followup.send(embed=embed)
        await db.log_action(interaction.guild_id, "UNBAN", interaction.user.id, uid, reason)

        s = await db.get_guild_settings(interaction.guild_id)
        if s and s.get("log_channel"):
            await send_log(interaction.guild, s["log_channel"], embed)

    # ── /massban ──────────────────────────────────────────────
    @app_commands.command(name="massban", description="Ban multiple users by their IDs (space-separated). Admin only.")
    @app_commands.describe(user_ids="Space-separated user IDs to ban", reason="Reason for mass ban")
    @app_commands.checks.has_permissions(administrator=True)
    async def massban(self, interaction: discord.Interaction,
                      user_ids: str, reason: str = "Mass ban"):
        await interaction.response.defer(ephemeral=True)

        ids = [x.strip() for x in user_ids.split() if x.strip().isdigit()]
        if not ids:
            await interaction.followup.send(embed=error_embed("No Valid IDs", "Provide space-separated numeric user IDs."), ephemeral=True)
            return
        if len(ids) > 20:
            await interaction.followup.send(embed=error_embed("Too Many", "Max 20 users per massban."), ephemeral=True)
            return

        banned, failed = [], []
        for uid_str in ids:
            try:
                uid = int(uid_str)
                user = await self.bot.fetch_user(uid)
                await interaction.guild.ban(user, reason=f"Massban by {interaction.user}: {reason}", delete_message_days=0)
                await db.log_action(interaction.guild_id, "BAN", interaction.user.id, uid, f"[MASSBAN] {reason}")
                banned.append(uid_str)
            except Exception:
                failed.append(uid_str)

        embed = success_embed("Mass Ban Complete",
            f"✅ Banned: `{'`, `'.join(banned)}`" if banned else "No users banned.")
        if failed:
            embed.add_field(name="❌ Failed", value=f"`{'`, `'.join(failed)}`", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── Error handler ─────────────────────────────────────────
    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            msg = "You need **Ban Members** permission to use this command."
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=error_embed("Missing Permissions", msg), ephemeral=True)
            else:
                await interaction.followup.send(embed=error_embed("Missing Permissions", msg), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Ban(bot))
