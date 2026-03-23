import discord
from discord import app_commands
from discord.ext import commands
import config

CATEGORIES = {
    "general": {
        "title": "🔧 General", "color": 0x5865F2,
        "cmds": [
            ("/ping",                 "Bot latency"),
            ("/avatar [@user]",       "View avatar"),
            ("/banner [@user]",       "View profile banner"),
            ("/uptime",               "Bot uptime"),
            ("/botinfo",              "About this bot"),
            ("/server",               "Server information"),
            ("/servericon",           "Server icon"),
            ("/serverbanner",         "Server banner"),
            ("/membercount",          "Member breakdown"),
            ("/userinfo [@user]",     "User details"),
            ("/roleinfo <@role>",     "Role details"),
            ("/emojiinfo <emoji>",    "Emoji details"),
            ("/snipe [index]",            "Last deleted message(s)"),
            ("/editsnipe",               "Last edited message"),
            ("/clearsnipe",              "Clear snipe cache (mod)"),
            ("/remind <dur> <text>",  "Set a reminder"),
            ("/reminders",            "View your reminders"),
            ("/remindcancel <id>",    "Cancel a reminder"),
            ("/afk [reason]",         "Set your AFK status"),
            ("/help [cat]",           "This menu"),
        ]
    },
    "mod": {
        "title": "🛡️ Moderation", "color": 0xED4245,
        "cmds": [
            ("/kick <@user>",          "Kick a member"),
            ("/ban <@user>",           "Ban a member"),
            ("/softban <@user>",       "Ban+unban to delete messages"),
            ("/massban <ids>",         "Ban multiple users by ID"),
            ("/unban <id>",            "Unban by ID"),
            ("/mute <@user> [dur]",    "Mute with role"),
            ("/unmute <@user>",        "Unmute a member"),
            ("/timeout <@user> <dur>", "Discord native timeout"),
            ("/untimeout <@user>",     "Remove timeout"),
            ("/warn <@user>",          "Issue a warning"),
            ("/warnings <@user>",      "View warnings"),
            ("/clearwarns <@user>",    "Clear all warnings"),
            ("/delwarn <id>",          "Delete one warning"),
            ("/note add <@user>",      "Add a mod note"),
            ("/note view <@user>",     "View mod notes"),
            ("/clear [n] [user] [bots] [text]", "Delete messages (with filters)"),
            ("/slowmode [s]",          "Set channel slowmode"),
            ("/lockdown [#ch]",        "Lock a channel"),
            ("/unlockdown [#ch]",      "Unlock a channel"),
            ("/warnthreshold set",     "Auto-action at warn count"),
            ("/warnthreshold list",    "View escalation rules"),
            ("/warnthreshold remove",  "Remove a threshold"),
        ]
    },
    "roles": {
        "title": "🎭 Roles", "color": 0x8b5cf6,
        "cmds": [
            ("/panels",          "List all role panels"),
            ("/autorole add",    "Add a join auto-role"),
            ("/autorole remove", "Remove auto-role"),
            ("/autorole list",   "List auto-roles"),
        ]
    },
    "temprooms": {
        "title": "🔊 Temp Rooms", "color": 0x3dffaa,
        "cmds": [
            ("/temproom setup",           "Configure temp rooms"),
            ("/temproom rename",          "Rename your room"),
            ("/temproom limit",           "Set user limit"),
            ("/temproom lock/unlock",     "Lock or unlock room"),
            ("/temproom kick/ban/unban",  "Manage room users"),
            ("/temproom transfer",        "Transfer ownership"),
            ("/temproom delete",          "Delete your room"),
            ("/temproom info",            "View room info"),
        ]
    },
    "music": {
        "title": "🎵 Music", "color": 0x1DB954,
        "cmds": [
            ("/play <query>",   "Play song or playlist"),
            ("/pause",          "Pause playback"),
            ("/resume",         "Resume playback"),
            ("/skip",           "Skip current track"),
            ("/stop",           "Stop and disconnect"),
            ("/queue",          "View the queue"),
            ("/nowplaying",     "Current track info"),
            ("/volume <0-150>", "Set playback volume"),
            ("/loop [mode]",    "Loop track or queue"),
            ("/shuffle",        "Toggle queue shuffle"),
            ("/remove <pos>",   "Remove track from queue"),
            ("/join",           "Join your voice channel"),
            ("/leave",          "Leave voice channel"),
        ]
    },
    "community": {
        "title": "💬 Community", "color": 0x5865F2,
        "cmds": [
            ("/automod toggle",           "Enable/disable AutoMod"),
            ("/automod spam",             "Configure spam detection"),
            ("/automod links",            "Configure link filter"),
            ("/automod words",            "Configure word filter"),
            ("/automod caps",             "Configure caps filter"),
            ("/automod mentions",         "Configure mention filter"),
            ("/automod exempt",           "Exempt roles or channels"),
            ("/automod status",           "View all automod settings"),
            ("/alias add <alias> <cmd>",  "Create a command alias"),
            ("/alias remove <alias>",     "Remove an alias"),
            ("/alias list",               "List all aliases"),
            ("/poll <question> [opts]",   "Create an interactive poll"),
            ("/endpoll <message_id>",     "End a poll early"),
            ("/gstart <prize> <dur>",     "Start a giveaway"),
            ("/gend <message_id>",        "End a giveaway early"),
            ("/greroll <message_id>",     "Reroll giveaway winners"),
            ("/glist",                    "List active giveaways"),
            ("/starboard <channel>",      "Set up the starboard"),
            ("/disablestarboard",         "Disable starboard"),
        ]
    },
    "security": {
        "title": "🔒 Security", "color": 0xe74c3c,
        "cmds": [
            ("/lockserver",   "Emergency server lockdown"),
            ("/unlockserver", "Unlock all channels"),
            ("/antiraid",     "Configure anti-raid"),
            ("/verification", "Set up verification gate"),
        ]
    },
    "settings": {
        "title": "⚙️ Settings", "color": 0x5865F2,
        "cmds": [
            ("/setlog [#ch]",   "Set mod log channel"),
            ("/setwelcome",     "Set welcome message"),
            ("/settings",       "View current settings"),
            ("/setupmute",      "Create or fix mute role"),
            ("/temproom setup", "Configure temp rooms"),
        ]
    },
}


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show all available commands grouped by category.")
    @app_commands.describe(category="Which category to show (leave empty for overview)")
    @app_commands.choices(category=[
        app_commands.Choice(name=v["title"], value=k) for k, v in CATEGORIES.items()
    ])
    async def help(self, interaction: discord.Interaction, category: str = None):
        if category and category in CATEGORIES:
            cat = CATEGORIES[category]
            embed = discord.Embed(title=f"{cat['title']} Commands", color=cat["color"])
            embed.description = "\n".join(f"`{cmd}` — {desc}" for cmd, desc in cat["cmds"])
            embed.set_footer(text="[ ] = optional  < > = required  •  Type / in chat to use")
        else:
            total = sum(len(v["cmds"]) for v in CATEGORIES.values())
            embed = discord.Embed(
                title="📚 Command Help",
                description=(
                    f"**{self.bot.user.name}** — `{total}` commands across "
                    f"`{len(CATEGORIES)}` categories.\n\n"
                    f"Use `/help [category]` for details, or type `/` in chat for autocomplete."
                ),
                color=config.Colors.PRIMARY
            )
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
            for cat in CATEGORIES.values():
                sample = ", ".join(f"`{c[0].split()[0]}`" for c in cat["cmds"][:3])
                embed.add_field(
                    name=cat["title"],
                    value=f"{len(cat['cmds'])} commands — {sample}…",
                    inline=True
                )
            embed.set_footer(
                text="[ ] = optional  < > = required  •  Type / in chat to use all commands")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
