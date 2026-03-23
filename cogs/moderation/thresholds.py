"""
cogs/moderation/thresholds.py
/warnthreshold set / list / remove
Configures automatic escalating punishments when a user's warn count hits a threshold.
e.g. 3 warns → mute 1h   |   5 warns → kick   |   7 warns → ban
Checked automatically by the warn cog after every warning.
"""
import discord
from discord import app_commands
from discord.ext import commands
from utils import db
from utils.helpers import success_embed, error_embed, base_embed
import config

threshold_group = app_commands.Group(
    name="warnthreshold",
    description="Configure automatic actions when users hit warn counts."
)

ACTION_CHOICES = [
    app_commands.Choice(name="Mute",  value="mute"),
    app_commands.Choice(name="Kick",  value="kick"),
    app_commands.Choice(name="Ban",   value="ban"),
]

DURATION_CHOICES = [
    app_commands.Choice(name="10 minutes",  value=600),
    app_commands.Choice(name="30 minutes",  value=1800),
    app_commands.Choice(name="1 hour",      value=3600),
    app_commands.Choice(name="6 hours",     value=21600),
    app_commands.Choice(name="12 hours",    value=43200),
    app_commands.Choice(name="1 day",       value=86400),
    app_commands.Choice(name="3 days",      value=259200),
    app_commands.Choice(name="7 days",      value=604800),
    app_commands.Choice(name="Permanent",   value=0),
]


def fmt_duration(secs: int | None) -> str:
    if not secs:
        return "Permanent"
    parts = []
    if secs >= 86400:  parts.append(f"{secs // 86400}d")
    if (secs % 86400) >= 3600: parts.append(f"{(secs % 86400) // 3600}h")
    if (secs % 3600) >= 60:    parts.append(f"{(secs % 3600) // 60}m")
    return " ".join(parts) or f"{secs}s"


class WarnThresholds(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @threshold_group.command(name="set", description="Set an automatic action at a warn count.")
    @app_commands.describe(
        count="Warning count that triggers this action (e.g. 3)",
        action="Action to take when count is reached",
        duration="Mute duration (only applies to 'mute' action)"
    )
    @app_commands.choices(action=ACTION_CHOICES, duration=DURATION_CHOICES)
    @app_commands.checks.has_permissions(administrator=True)
    async def threshold_set(
        self,
        interaction: discord.Interaction,
        count: app_commands.Range[int, 1, 50],
        action: str,
        duration: int = 3600
    ):
        dur = None if action != "mute" else (duration or None)

        await db.set_warn_threshold(interaction.guild_id, count, action, dur)

        desc = f"At **{count} warnings** → **{action.upper()}**"
        if action == "mute" and dur:
            desc += f" for **{fmt_duration(dur)}**"
        elif action == "mute":
            desc += " (permanent)"

        embed = success_embed("Threshold Set", desc)
        embed.set_footer(text=f"Use /warnthreshold list to see all thresholds • {config.FOOTER_TEXT}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @threshold_group.command(name="list", description="View all configured warn thresholds.")
    async def threshold_list(self, interaction: discord.Interaction):
        thresholds = await db.get_warn_thresholds(interaction.guild_id)
        embed = base_embed(f"⚠️ Warn Thresholds — {interaction.guild.name}")

        if not thresholds:
            embed.description = (
                "No automatic thresholds configured.\n"
                "Use `/warnthreshold set` to add one.\n\n"
                "**Example:** 3 warnings → mute 1h → 5 warnings → kick → 7 warnings → ban"
            )
        else:
            lines = []
            for t in thresholds:
                action_str = t["action"].upper()
                if t["action"] == "mute":
                    action_str += f" ({fmt_duration(t['duration'])})"
                lines.append(f"**{t['count']} warns** → {action_str}")
            embed.description = "\n".join(lines)
            embed.set_footer(text=f"{len(thresholds)} threshold(s) active • {config.FOOTER_TEXT}")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @threshold_group.command(name="remove", description="Remove a threshold at a specific warn count.")
    @app_commands.describe(count="The warning count to remove the threshold for")
    @app_commands.checks.has_permissions(administrator=True)
    async def threshold_remove(
        self,
        interaction: discord.Interaction,
        count: app_commands.Range[int, 1, 50]
    ):
        thresholds = await db.get_warn_thresholds(interaction.guild_id)
        if not any(t["count"] == count for t in thresholds):
            await interaction.response.send_message(
                embed=error_embed("Not Found", f"No threshold at **{count} warnings**."),
                ephemeral=True)
            return

        await db.delete_warn_threshold(interaction.guild_id, count)
        await interaction.response.send_message(
            embed=success_embed("Removed", f"Threshold at **{count} warnings** deleted."),
            ephemeral=True)

    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=error_embed("Missing Permissions", "You need **Administrator** for this."),
                    ephemeral=True)


async def setup(bot: commands.Bot):
    bot.tree.add_command(threshold_group)
    await bot.add_cog(WarnThresholds(bot))
