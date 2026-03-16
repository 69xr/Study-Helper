"""
cogs/suggestions.py
Commands: /suggest  /suggestion approve  /suggestion deny  /suggestsetup
"""
import discord
from discord import app_commands
from discord.ext import commands
from utils import db
from utils.helpers import success_embed, error_embed

suggestion_group = app_commands.Group(name="suggestion", description="Manage suggestions.")

STATUS_COLORS = {"pending": 0x5865F2, "approved": 0x57F287, "denied": 0xED4245}
STATUS_EMOJI  = {"pending": "🔵", "approved": "✅", "denied": "❌"}


def build_suggestion_embed(suggestion: dict, author: discord.User | discord.Member | None = None) -> discord.Embed:
    status = suggestion.get("status", "pending")
    color  = STATUS_COLORS.get(status, 0x5865F2)
    emoji  = STATUS_EMOJI.get(status, "🔵")

    embed = discord.Embed(
        title=f"{emoji} Suggestion #{suggestion['id']}",
        description=suggestion["content"],
        color=color
    )
    if author:
        embed.set_author(name=str(author), icon_url=getattr(author, "display_avatar", author.default_avatar).url)
    else:
        embed.set_author(name=f"User {suggestion['author_id']}")

    yes = suggestion.get("yes_votes", 0)
    no  = suggestion.get("no_votes",  0)
    total = yes + no
    if total > 0:
        pct = int(yes / total * 100)
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        embed.add_field(name="Votes", value=f"✅ `{yes}` · ❌ `{no}`  |  `{bar}` {pct}%", inline=False)
    else:
        embed.add_field(name="Votes", value="✅ `0` · ❌ `0`  |  No votes yet", inline=False)

    if status != "pending" and suggestion.get("mod_note"):
        label = "Approval Note" if status == "approved" else "Denial Reason"
        embed.add_field(name=label, value=suggestion["mod_note"], inline=False)

    embed.set_footer(text=f"Status: {status.upper()} • ID: {suggestion['id']}")
    return embed


class SuggestionVoteView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(emoji="✅", label="Upvote", style=discord.ButtonStyle.success, custom_id="sug_upvote")
    async def upvote(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_vote(interaction, "up")

    @discord.ui.button(emoji="❌", label="Downvote", style=discord.ButtonStyle.danger, custom_id="sug_downvote")
    async def downvote(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_vote(interaction, "down")

    async def _handle_vote(self, interaction: discord.Interaction, vote: str):
        sug = await db.get_suggestion_by_message(interaction.message.id)
        if not sug:
            await interaction.response.send_message(embed=error_embed("Suggestion not found."), ephemeral=True)
            return
        if sug["status"] != "pending":
            await interaction.response.send_message(
                embed=error_embed("Closed", "This suggestion has already been decided."), ephemeral=True)
            return
        # Simple vote toggle — increment the count
        yes = sug["yes_votes"]
        no  = sug["no_votes"]
        if vote == "up":
            yes += 1
        else:
            no += 1
        await db.update_suggestion_votes(sug["id"], yes, no)
        updated = await db.get_suggestion(sug["id"])
        try:
            await interaction.message.edit(embed=build_suggestion_embed(updated))
        except Exception:
            pass
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"{'✅ Upvoted' if vote == 'up' else '❌ Downvoted'}! Total: ✅ {yes} · ❌ {no}",
                color=0x57F287 if vote == "up" else 0xED4245
            ),
            ephemeral=True)


class Suggestions(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(SuggestionVoteView())

    # ── /suggest ──────────────────────────────────────────
    @app_commands.command(name="suggest", description="Submit a suggestion for the server.")
    @app_commands.describe(suggestion="Your suggestion (be specific!)")
    async def suggest(self, interaction: discord.Interaction, suggestion: str):
        await interaction.response.defer(ephemeral=True)
        settings = await db.get_suggestion_settings(interaction.guild_id)
        if not settings.get("channel_id"):
            await interaction.followup.send(
                embed=error_embed("Not Configured",
                    "The suggestions channel hasn't been set up yet.\nAsk an admin to run `/suggestsetup`."),
                ephemeral=True)
            return

        channel = interaction.guild.get_channel(settings["channel_id"])
        if not channel:
            await interaction.followup.send(embed=error_embed("Channel not found."), ephemeral=True)
            return

        sug_id = await db.create_suggestion(interaction.guild_id, channel.id, interaction.user.id, suggestion)
        sug    = await db.get_suggestion(sug_id)
        embed  = build_suggestion_embed(sug, interaction.user)
        msg    = await channel.send(embed=embed, view=SuggestionVoteView())
        await db.set_suggestion_message(sug_id, msg.id)

        await interaction.followup.send(
            embed=success_embed("Suggestion Submitted! 💡",
                f"Your suggestion has been posted in {channel.mention}.\n**ID:** `{sug_id}`"),
            ephemeral=True)

    # ── /suggestion approve ───────────────────────────────
    @suggestion_group.command(name="approve", description="Approve a suggestion.")
    @app_commands.describe(suggestion_id="The suggestion ID", note="Optional approval note")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def approve(self, interaction: discord.Interaction, suggestion_id: int, note: str = ""):
        sug = await db.get_suggestion(suggestion_id)
        if not sug or str(sug["guild_id"]) != str(interaction.guild_id):
            await interaction.response.send_message(embed=error_embed("Not Found"), ephemeral=True)
            return
        await db.decide_suggestion(suggestion_id, "approved", interaction.user.id, note)
        updated = await db.get_suggestion(suggestion_id)
        # Update original message
        channel = interaction.guild.get_channel(sug["channel_id"])
        if channel and sug.get("message_id"):
            try:
                author = await self.bot.fetch_user(sug["author_id"])
                msg = await channel.fetch_message(sug["message_id"])
                await msg.edit(embed=build_suggestion_embed(updated, author), view=None)
            except Exception:
                pass
        # DM author if enabled
        settings = await db.get_suggestion_settings(interaction.guild_id)
        if settings.get("dm_on_decision"):
            try:
                author = await self.bot.fetch_user(sug["author_id"])
                dm_embed = discord.Embed(
                    title="✅ Your Suggestion Was Approved!",
                    description=f"**Suggestion:** {sug['content']}\n**Server:** {interaction.guild.name}",
                    color=0x57F287
                )
                if note: dm_embed.add_field(name="Note from staff", value=note)
                await author.send(embed=dm_embed)
            except Exception:
                pass
        await interaction.response.send_message(
            embed=success_embed("Approved", f"Suggestion `#{suggestion_id}` approved."), ephemeral=True)

    # ── /suggestion deny ──────────────────────────────────
    @suggestion_group.command(name="deny", description="Deny a suggestion.")
    @app_commands.describe(suggestion_id="The suggestion ID", reason="Reason for denial")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def deny(self, interaction: discord.Interaction, suggestion_id: int, reason: str = ""):
        sug = await db.get_suggestion(suggestion_id)
        if not sug or str(sug["guild_id"]) != str(interaction.guild_id):
            await interaction.response.send_message(embed=error_embed("Not Found"), ephemeral=True)
            return
        await db.decide_suggestion(suggestion_id, "denied", interaction.user.id, reason)
        updated = await db.get_suggestion(suggestion_id)
        channel = interaction.guild.get_channel(sug["channel_id"])
        if channel and sug.get("message_id"):
            try:
                author = await self.bot.fetch_user(sug["author_id"])
                msg    = await channel.fetch_message(sug["message_id"])
                await msg.edit(embed=build_suggestion_embed(updated, author), view=None)
            except Exception:
                pass
        settings = await db.get_suggestion_settings(interaction.guild_id)
        if settings.get("dm_on_decision"):
            try:
                author = await self.bot.fetch_user(sug["author_id"])
                dm_embed = discord.Embed(
                    title="❌ Your Suggestion Was Denied",
                    description=f"**Suggestion:** {sug['content']}\n**Server:** {interaction.guild.name}",
                    color=0xED4245
                )
                if reason: dm_embed.add_field(name="Reason", value=reason)
                await author.send(embed=dm_embed)
            except Exception:
                pass
        await interaction.response.send_message(
            embed=success_embed("Denied", f"Suggestion `#{suggestion_id}` denied."), ephemeral=True)

    # ── /suggestsetup ─────────────────────────────────────
    @app_commands.command(name="suggestsetup", description="Configure the suggestions system.")
    @app_commands.describe(
        channel="Channel where suggestions are posted",
        dm_author="DM the author when their suggestion is approved/denied"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def suggestsetup(self, interaction: discord.Interaction,
                            channel: discord.TextChannel,
                            dm_author: bool = True):
        await db.set_suggestion_setting(interaction.guild_id, "channel_id", channel.id)
        await db.set_suggestion_setting(interaction.guild_id, "dm_on_decision", int(dm_author))
        embed = success_embed("Suggestions Configured")
        embed.add_field(name="Channel",   value=channel.mention,           inline=True)
        embed.add_field(name="DM Author", value="✅ Yes" if dm_author else "❌ No", inline=True)
        embed.description = "Members can now use `/suggest <text>` to submit suggestions."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=error_embed("Missing Permissions"), ephemeral=True)


async def setup(bot: commands.Bot):
    bot.tree.add_command(suggestion_group)
    await bot.add_cog(Suggestions(bot))
