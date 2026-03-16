import discord
from discord import app_commands
from discord.ext import commands
from utils import db
from utils.helpers import mod_embed, error_embed, send_log

class Ban(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="ban", description="Ban a member from the server.")
    @app_commands.describe(member="Member to ban", reason="Reason", delete_days="Days of messages to delete (0-7)")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction,
                  member: discord.Member, reason: str = "No reason provided",
                  delete_days: app_commands.Range[int, 0, 7] = 0):
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                embed=error_embed("Can't Ban", "That member's role is too high for me to ban."), ephemeral=True)
            return
        try:
            await member.send(embed=discord.Embed(
                title=f"🔨 Banned from {interaction.guild.name}",
                description=f"**Reason:** {reason}", color=0xED4245))
        except discord.Forbidden:
            pass
        await member.ban(reason=f"{interaction.user}: {reason}", delete_message_days=delete_days)
        await db.log_action(interaction.guild_id, "BAN", interaction.user.id, member.id, reason)
        embed = mod_embed("🔨  Member Banned", member, interaction.user, reason, 0xED4245)
        await interaction.response.send_message(embed=embed)
        s = await db.get_guild_settings(interaction.guild_id)
        if s and s.get("log_channel"):
            await send_log(interaction.guild, s["log_channel"], embed)

    @app_commands.command(name="unban", description="Unban a user by their ID.")
    @app_commands.describe(user_id="The user's Discord ID", reason="Reason for unban")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction,
                    user_id: str, reason: str = "No reason provided"):
        try:
            uid = int(user_id)
        except ValueError:
            await interaction.response.send_message(
                embed=error_embed("Invalid ID", "That's not a valid user ID."), ephemeral=True)
            return
        try:
            user = await self.bot.fetch_user(uid)
            await interaction.guild.unban(user, reason=f"{interaction.user}: {reason}")
        except discord.NotFound:
            await interaction.response.send_message(
                embed=error_embed("Not Banned", "That user is not banned."), ephemeral=True)
            return
        embed = discord.Embed(title="✅  User Unbanned", color=0x57F287)
        embed.add_field(name="User",   value=f"`{user}` (`{user.id}`)", inline=True)
        embed.add_field(name="Mod",    value=interaction.user.mention,  inline=True)
        embed.add_field(name="Reason", value=reason,                    inline=False)
        await interaction.response.send_message(embed=embed)
        await db.log_action(interaction.guild_id, "UNBAN", interaction.user.id, uid, reason)

    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=error_embed("Missing Permissions"), ephemeral=True)

async def setup(bot): await bot.add_cog(Ban(bot))
