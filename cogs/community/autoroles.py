"""
cogs/community/autoroles.py
Automatically assign roles when a member joins.
/autorole add  /autorole remove  /autorole list
"""
import discord
from discord import app_commands
from discord.ext import commands
from utils import db
from utils.helpers import success_embed, error_embed, base_embed
import config

autorole_group = app_commands.Group(name="autorole", description="Manage auto-assigned roles for new members.")


class AutoRoles(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Assign configured auto-roles to new members."""
        role_ids = await db.get_auto_roles(member.guild.id)
        if not role_ids:
            return
        roles_to_add = []
        for rid in role_ids:
            role = member.guild.get_role(rid)
            if role and role < member.guild.me.top_role:
                roles_to_add.append(role)
        if roles_to_add:
            try:
                await member.add_roles(*roles_to_add, reason="Auto-role on join")
            except discord.Forbidden:
                pass

    @autorole_group.command(name="add", description="Add a role to auto-assign on member join.")
    @app_commands.describe(role="Role to automatically assign to new members")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def autorole_add(self, interaction: discord.Interaction, role: discord.Role):
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                embed=error_embed("Can't Add", "That role is higher than my top role."), ephemeral=True)
            return
        if role.managed:
            await interaction.response.send_message(
                embed=error_embed("Can't Add", "Can't auto-assign managed/bot roles."), ephemeral=True)
            return

        role_ids = await db.get_auto_roles(interaction.guild_id)
        if role.id in role_ids:
            await interaction.response.send_message(
                embed=error_embed("Already Added", f"{role.mention} is already an auto-role."),
                ephemeral=True)
            return
        if len(role_ids) >= 10:
            await interaction.response.send_message(
                embed=error_embed("Limit Reached", "Maximum 10 auto-roles per server."), ephemeral=True)
            return

        role_ids.append(role.id)
        await db.set_auto_roles(interaction.guild_id, role_ids)
        await interaction.response.send_message(
            embed=success_embed("Auto-Role Added",
                f"{role.mention} will now be assigned to all new members."),
            ephemeral=True)

    @autorole_group.command(name="remove", description="Remove a role from auto-assign.")
    @app_commands.describe(role="Role to remove from auto-assign")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def autorole_remove(self, interaction: discord.Interaction, role: discord.Role):
        role_ids = await db.get_auto_roles(interaction.guild_id)
        if role.id not in role_ids:
            await interaction.response.send_message(
                embed=error_embed("Not Found", f"{role.mention} is not an auto-role."), ephemeral=True)
            return
        role_ids.remove(role.id)
        await db.set_auto_roles(interaction.guild_id, role_ids)
        await interaction.response.send_message(
            embed=success_embed("Removed", f"{role.mention} removed from auto-roles."), ephemeral=True)

    @autorole_group.command(name="list", description="View all auto-roles for this server.")
    async def autorole_list(self, interaction: discord.Interaction):
        role_ids = await db.get_auto_roles(interaction.guild_id)
        embed = base_embed(f"🎭 Auto-Roles — {interaction.guild.name}")
        if not role_ids:
            embed.description = (
                "No auto-roles configured.\n"
                "Use `/autorole add @role` to add one.")
        else:
            roles = []
            for rid in role_ids:
                role = interaction.guild.get_role(rid)
                roles.append(role.mention if role else f"`Deleted Role ({rid})`")
            embed.description = "\n".join(f"• {r}" for r in roles)
            embed.set_footer(text=f"{len(role_ids)} auto-role(s) • assigned on member join • {config.FOOTER_TEXT}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=error_embed("Missing Permissions", "You need **Manage Roles** for this."),
                    ephemeral=True)


async def setup(bot):
    bot.tree.add_command(autorole_group)
    await bot.add_cog(AutoRoles(bot))
