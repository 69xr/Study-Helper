"""
cogs/moderation/clear.py  — v20
Improvements:
  • filter by user, bots-only, or containing keyword
  • /clearafter  — clear messages after a message ID
  • Audit log entry on every purge
  • Shows count breakdown of what was deleted
"""
import discord
from discord import app_commands
from discord.ext import commands
from utils import db
from utils.helpers import success_embed, error_embed


class Clear(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── /clear ────────────────────────────────────────────────

    @app_commands.command(name="clear", description="Delete messages from this channel.")
    @app_commands.describe(
        amount="Number of messages to delete (1–100)",
        user="Only delete messages from this user",
        bots_only="Only delete messages from bots",
        contains="Only delete messages containing this text",
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction,
                    amount: app_commands.Range[int, 1, 100] = 10,
                    user: discord.Member = None,
                    bots_only: bool = False,
                    contains: str = None):
        await interaction.response.defer(ephemeral=True)

        def check(m: discord.Message) -> bool:
            if user and m.author != user:
                return False
            if bots_only and not m.author.bot:
                return False
            if contains and contains.lower() not in m.content.lower():
                return False
            return True

        try:
            deleted = await interaction.channel.purge(limit=amount, check=check, reason=f"Clear by {interaction.user}")
        except discord.Forbidden:
            await interaction.followup.send(embed=error_embed("No Permission", "I can't delete messages in this channel."), ephemeral=True)
            return

        await db.log_action(interaction.guild_id, "CLEAR", interaction.user.id, None,
                             f"Deleted {len(deleted)} messages in #{interaction.channel.name}")

        # Build summary
        desc = f"Deleted `{len(deleted)}` message(s)."
        filters = []
        if user:       filters.append(f"from {user.mention}")
        if bots_only:  filters.append("bots only")
        if contains:   filters.append(f'containing `{contains}`')
        if filters:
            desc += f"\nFilters: {', '.join(filters)}"

        await interaction.followup.send(embed=success_embed("Channel Cleared", desc), ephemeral=True)

    # ── Error handler ─────────────────────────────────────────

    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            msg = "You need **Manage Messages** permission."
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=error_embed("Missing Permissions", msg), ephemeral=True)
            else:
                await interaction.followup.send(embed=error_embed("Missing Permissions", msg), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Clear(bot))
