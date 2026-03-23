"""
cogs/moderation/notes.py
Private moderator notes on users. Only mods can see them.
/note add  /note list  /note delete
"""
import discord
from discord import app_commands
from discord.ext import commands
from utils import db
from utils.helpers import success_embed, error_embed, base_embed
import config

note_group = app_commands.Group(name="note", description="Manage private moderator notes on users.")


class Notes(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @note_group.command(name="add", description="Add a private mod note to a user.")
    @app_commands.describe(user="Target user", note="Note content (only mods can see this)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def note_add(self, interaction: discord.Interaction,
                        user: discord.Member, note: str):
        note_id = await db.add_mod_note(interaction.guild_id, user.id, interaction.user.id, note)
        embed = success_embed("📝 Note Added",
                              f"Note `#{note_id}` added for {user.mention}.")
        embed.add_field(name="Content", value=note, inline=False)
        embed.set_thumbnail(url=user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @note_group.command(name="list", description="View all mod notes for a user.")
    @app_commands.describe(user="User to look up")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def note_list(self, interaction: discord.Interaction, user: discord.Member):
        notes = await db.get_mod_notes(interaction.guild_id, user.id)
        embed = base_embed(f"📝 Notes — {user.display_name}")
        embed.set_thumbnail(url=user.display_avatar.url)
        if not notes:
            embed.description = f"No notes for {user.mention}."
        else:
            for n in notes[:10]:
                mod = interaction.guild.get_member(n["mod_id"])
                mod_str = str(mod) if mod else f"ID:{n['mod_id']}"
                embed.add_field(
                    name=f"#{n['id']} — {n['created_at'][:10]} by {mod_str}",
                    value=n["note"][:1024],
                    inline=False)
            embed.set_footer(text=f"{len(notes)} note(s) • {config.FOOTER_TEXT}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @note_group.command(name="delete", description="Delete a mod note by ID.")
    @app_commands.describe(note_id="Note ID (from /note list)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def note_delete(self, interaction: discord.Interaction, note_id: int):
        removed = await db.delete_mod_note(note_id, interaction.guild_id)
        if not removed:
            await interaction.response.send_message(
                embed=error_embed("Not Found", f"Note `#{note_id}` not found in this server."),
                ephemeral=True)
            return
        await interaction.response.send_message(
            embed=success_embed("Deleted", f"Note `#{note_id}` removed."),
            ephemeral=True)

    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=error_embed("Missing Permissions"), ephemeral=True)


async def setup(bot):
    bot.tree.add_command(note_group)
    await bot.add_cog(Notes(bot))
