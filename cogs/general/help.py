import discord
from discord import app_commands
from discord.ext import commands

import config
from utils.helpers import base_embed

SECTION_ORDER = [
    "Getting Started",
    "Moderation",
    "Community",
    "Focus",
    "Music",
    "Utility",
    "Owner",
    "Other",
]

COMMAND_SECTIONS = {
    "ping": "Getting Started",
    "help": "Getting Started",
    "server": "Getting Started",
    "servericon": "Getting Started",
    "serverbanner": "Getting Started",
    "membercount": "Getting Started",
    "userinfo": "Getting Started",
    "avatar": "Getting Started",
    "banner": "Getting Started",
    "botinfo": "Getting Started",
    "uptime": "Getting Started",
    "roleinfo": "Getting Started",
    "roles": "Getting Started",
    "emojiinfo": "Getting Started",
    "kick": "Moderation",
    "ban": "Moderation",
    "softban": "Moderation",
    "massban": "Moderation",
    "unban": "Moderation",
    "mute": "Moderation",
    "unmute": "Moderation",
    "timeout": "Moderation",
    "untimeout": "Moderation",
    "warn": "Moderation",
    "warnings": "Moderation",
    "clearwarns": "Moderation",
    "delwarn": "Moderation",
    "clear": "Moderation",
    "slowmode": "Moderation",
    "lockdown": "Moderation",
    "unlockdown": "Moderation",
    "note": "Moderation",
    "warnthreshold": "Moderation",
    "lockserver": "Moderation",
    "unlockserver": "Moderation",
    "automod": "Community",
    "autorole": "Community",
    "cc": "Community",
    "alias": "Community",
    "poll": "Community",
    "endpoll": "Community",
    "starboard": "Community",
    "disablestarboard": "Community",
    "temproom": "Community",
    "invite": "Community",
    "remind": "Utility",
    "reminders": "Utility",
    "remindcancel": "Utility",
    "afk": "Utility",
    "snipe": "Utility",
    "editsnipe": "Utility",
    "clearsnipe": "Utility",
    "timer": "Focus",
    "activesessions": "Focus",
    "profile": "Focus",
    "focusxp": "Focus",
    "focusrank": "Focus",
    "history": "Focus",
    "streak": "Focus",
    "pets": "Focus",
    "petshop": "Focus",
    "renamepet": "Focus",
    "play": "Music",
    "pause": "Music",
    "resume": "Music",
    "skip": "Music",
    "stop": "Music",
    "queue": "Music",
    "nowplaying": "Music",
    "volume": "Music",
    "loop": "Music",
    "shuffle": "Music",
    "remove": "Music",
    "clearqueue": "Music",
    "join": "Music",
    "leave": "Music",
    "lyrics": "Music",
    "blacklist": "Owner",
    "unblacklist": "Owner",
    "blacklistview": "Owner",
    "reload": "Owner",
    "shutdown": "Owner",
    "announce": "Owner",
    "botstats": "Owner",
    "dm": "Owner",
}

SECTION_COLORS = {
    "Getting Started": config.Colors.PRIMARY,
    "Moderation": config.Colors.MOD,
    "Community": 0x7A6BFF,
    "Focus": 0x38C8F8,
    "Music": config.Colors.MUSIC,
    "Utility": config.Colors.INFO,
    "Owner": config.Colors.GOLD,
    "Other": config.Colors.NEUTRAL,
}


def _section_for(command_name: str) -> str:
    return COMMAND_SECTIONS.get(command_name, "Other")


def _render_signature(command: app_commands.Command | app_commands.Group) -> str:
    if isinstance(command, app_commands.Group):
        return f"/{command.name}"

    parts = [f"/{command.qualified_name}"]
    for param in command.parameters:
        if param.required:
            parts.append(f"<{param.display_name}>")
        else:
            parts.append(f"[{param.display_name}]")
    return " ".join(parts)


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _group_commands(self) -> dict[str, list[app_commands.Command | app_commands.Group]]:
        grouped = {section: [] for section in SECTION_ORDER}
        for command in sorted(self.bot.tree.get_commands(), key=lambda cmd: cmd.name):
            grouped[_section_for(command.name)].append(command)
        return grouped

    @app_commands.command(name="help", description="Browse the live Severus command catalog.")
    @app_commands.describe(section="Filter the help menu to a specific section")
    @app_commands.choices(
        section=[
            app_commands.Choice(name=section, value=section)
            for section in SECTION_ORDER
        ]
    )
    async def help(self, interaction: discord.Interaction, section: str | None = None):
        grouped = self._group_commands()
        total_commands = sum(len(commands_) for commands_ in grouped.values())

        if section:
            commands_ = grouped.get(section, [])
            embed = base_embed(
                title=f"{section} Commands",
                color=SECTION_COLORS.get(section, config.Colors.PRIMARY),
            )
            if commands_:
                embed.description = "\n".join(
                    f"`{_render_signature(command)}`\n{command.description or 'No description provided.'}"
                    for command in commands_
                )
            else:
                embed.description = "No commands are currently registered in this section."
            embed.add_field(
                name="Usage Notes",
                value="Use `/` in Discord for autocomplete. Angle brackets are required and square brackets are optional.",
                inline=False,
            )
            embed.set_thumbnail(url=interaction.client.user.display_avatar.url)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = base_embed(
            title="Severus Command Center",
            description=(
                f"Live slash command index for **{interaction.guild.name if interaction.guild else interaction.client.user.name}**.\n"
                f"`{total_commands}` top-level commands and groups are currently available."
            ),
            color=config.Colors.PRIMARY,
        )
        embed.set_thumbnail(url=interaction.client.user.display_avatar.url)

        for section_name in SECTION_ORDER:
            commands_ = grouped.get(section_name, [])
            if not commands_:
                continue
            preview = ", ".join(f"`/{command.name}`" for command in commands_[:4])
            if len(commands_) > 4:
                preview += f", +{len(commands_) - 4} more"
            embed.add_field(
                name=f"{section_name} ({len(commands_)})",
                value=preview,
                inline=True,
            )

        embed.add_field(
            name="Quick Start",
            value="Use `/help <section>` for a focused list, or type `/` in chat to browse command autocomplete.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
