import discord
from discord import app_commands
from discord.ext import commands
import config
from utils.helpers import base_embed

SECTIONS = [
    {
        "name": "Getting Started",
        "emoji": "🚀",
        "color": config.Colors.PRIMARY,
        "description": "Basic info commands and server utilities.",
        "commands": [
            "ping", "help", "botinfo", "uptime",
            "userinfo", "avatar", "banner",
            "server", "servericon", "serverbanner", "membercount",
            "roleinfo", "roles", "emojiinfo",
        ],
    },
    {
        "name": "Moderation",
        "emoji": "🛡️",
        "color": config.Colors.MOD,
        "description": "Tools to moderate members and maintain order.",
        "commands": [
            "kick", "ban", "softban", "massban", "unban",
            "mute", "unmute", "timeout", "untimeout",
            "warn", "warnings", "clearwarns", "delwarn",
            "clear", "slowmode", "lockdown", "unlockdown",
            "lockserver", "unlockserver",
            "note", "warnthreshold",
        ],
    },
    {
        "name": "Community",
        "emoji": "🏘️",
        "color": 0x7A6BFF,
        "description": "Server features, automation, and engagement tools.",
        "commands": [
            "automod", "autorole", "cc", "alias",
            "poll", "endpoll", "starboard", "disablestarboard",
            "temproom", "invite",
        ],
    },
    {
        "name": "Focus",
        "emoji": "🎯",
        "color": 0x38C8F8,
        "description": "Study timers, XP, streaks, and pet companions.",
        "commands": [
            "timer", "activesessions",
            "profile", "focusxp", "focusrank", "history", "streak",
            "pets", "petshop", "renamepet",
        ],
    },
    {
        "name": "Music",
        "emoji": "🎵",
        "color": config.Colors.MUSIC,
        "description": "Play and control music in voice channels.",
        "commands": [
            "play", "pause", "resume", "skip", "stop",
            "queue", "nowplaying", "volume", "loop", "shuffle",
            "remove", "clearqueue", "join", "leave", "lyrics",
        ],
    },
    {
        "name": "Utility",
        "emoji": "🔧",
        "color": config.Colors.INFO,
        "description": "Reminders, AFK status, and message tools.",
        "commands": ["remind", "reminders", "remindcancel", "afk", "snipe", "editsnipe", "clearsnipe"],
    },
    {
        "name": "Owner",
        "emoji": "👑",
        "color": config.Colors.GOLD,
        "description": "Bot owner administration commands.",
        "commands": ["blacklist", "unblacklist", "blacklistview", "reload", "shutdown", "announce", "botstats", "dm"],
    },
]

COMMAND_TO_SECTION: dict[str, dict] = {}
for _s in SECTIONS:
    for _cmd in _s["commands"]:
        COMMAND_TO_SECTION[_cmd] = _s


def _sig(command: app_commands.Command | app_commands.Group) -> str:
    if isinstance(command, app_commands.Group):
        return f"`/{command.name}`"
    parts = [f"/{command.qualified_name}"]
    for p in command.parameters:
        parts.append(f"<{p.display_name}>" if p.required else f"[{p.display_name}]")
    return f"`{' '.join(parts)}`"


def _section_embed(section: dict, commands_: list) -> discord.Embed:
    embed = discord.Embed(
        title=f"{section['emoji']} {section['name']}",
        description=section["description"],
        color=section["color"],
    )
    if commands_:
        lines = []
        for cmd in commands_:
            desc = cmd.description or "No description."
            lines.append(f"{_sig(cmd)}\n{desc}")
        embed.add_field(name=f"{len(commands_)} Commands", value="\n\n".join(lines), inline=False)
    else:
        embed.add_field(name="No Commands", value="No commands are currently loaded in this section.", inline=False)
    embed.set_footer(text="<required>  [optional]  •  Use / in Discord for autocomplete")
    return embed


def _overview_embed(bot: commands.Bot, guild: discord.Guild | None, grouped: dict) -> discord.Embed:
    total = sum(len(v) for v in grouped.values())
    embed = discord.Embed(
        title="📖 Severus — Command Center",
        description=(
            f"**{total}** commands across **{len(SECTIONS)}** sections.\n"
            "Use the dropdown below to browse a section, or pick one with `/help section:`."
        ),
        color=config.Colors.PRIMARY,
    )
    embed.set_thumbnail(url=bot.user.display_avatar.url)
    for section in SECTIONS:
        cmds = grouped.get(section["name"], [])
        if not cmds:
            continue
        preview = "  ".join(f"`/{c.name}`" for c in cmds[:4])
        if len(cmds) > 4:
            preview += f"  *+{len(cmds) - 4} more*"
        embed.add_field(
            name=f"{section['emoji']} {section['name']} ({len(cmds)})",
            value=preview or "*No commands loaded*",
            inline=True,
        )
    embed.set_footer(text="Tip: type / in Discord to browse all commands with autocomplete")
    return embed


class SectionDropdown(discord.ui.Select):
    def __init__(self, grouped: dict):
        self.grouped = grouped
        options = [
            discord.SelectOption(
                label=s["name"],
                emoji=s["emoji"],
                description=s["description"][:50],
                value=s["name"],
            )
            for s in SECTIONS
        ]
        super().__init__(placeholder="Browse a section…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        name = self.values[0]
        section = next((s for s in SECTIONS if s["name"] == name), None)
        if not section:
            return
        cmds = self.grouped.get(name, [])
        await interaction.response.edit_message(
            embed=_section_embed(section, cmds),
            view=SectionView(self.grouped, active=name),
        )


class BackButton(discord.ui.Button):
    def __init__(self, bot: commands.Bot, grouped: dict):
        super().__init__(label="Overview", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
        self.bot = bot
        self.grouped = grouped

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=_overview_embed(self.bot, interaction.guild, self.grouped),
            view=OverviewView(self.bot, self.grouped),
        )


class SectionView(discord.ui.View):
    def __init__(self, grouped: dict, active: str = None):
        super().__init__(timeout=120)
        self.add_item(SectionDropdown(grouped))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class OverviewView(discord.ui.View):
    def __init__(self, bot: commands.Bot, grouped: dict):
        super().__init__(timeout=120)
        self.add_item(SectionDropdown(grouped))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _grouped(self) -> dict[str, list]:
        result = {s["name"]: [] for s in SECTIONS}
        result["Other"] = []
        for command in sorted(self.bot.tree.get_commands(), key=lambda c: c.name):
            section = COMMAND_TO_SECTION.get(command.name)
            if section:
                result[section["name"]].append(command)
            else:
                result["Other"].append(command)
        return result

    @app_commands.command(name="help", description="Browse the full Severus command catalog.")
    @app_commands.describe(section="Jump directly to a specific section")
    @app_commands.choices(section=[
        app_commands.Choice(name=f"{s['emoji']} {s['name']}", value=s["name"])
        for s in SECTIONS
    ])
    async def help(self, interaction: discord.Interaction, section: str | None = None):
        grouped = self._grouped()

        if section:
            sec = next((s for s in SECTIONS if s["name"] == section), None)
            if not sec:
                await interaction.response.send_message(
                    embed=discord.Embed(description="❌ Unknown section.", color=config.Colors.ERROR),
                    ephemeral=True,
                )
                return
            cmds = grouped.get(section, [])
            await interaction.response.send_message(
                embed=_section_embed(sec, cmds),
                view=SectionView(grouped, active=section),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=_overview_embed(self.bot, interaction.guild, grouped),
            view=OverviewView(self.bot, grouped),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
