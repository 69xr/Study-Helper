import discord
from discord import app_commands
from discord.ext import commands

CATEGORIES = {
    "general": {
        "title": "🔧 General", "color": 0x5865F2,
        "cmds": [
            ("/ping","Bot latency"), ("/avatar [@user]","View avatar"),
            ("/banner [@user]","View profile banner"), ("/uptime","Bot uptime & stats"),
            ("/botinfo","About this bot"), ("/membercount","Member breakdown"),
            ("/server","Server info"), ("/servericon","Server icon"),
            ("/serverbanner","Server banner"), ("/userinfo [@user]","User details"),
            ("/roleinfo <@role>","Role details"), ("/emojiinfo <emoji>","Emoji info"),
            ("/roles","List all server roles"), ("/snipe","Last deleted message"),
            ("/help [cat]","This menu"),
        ]
    },
    "mod": {
        "title": "🛡️ Moderation", "color": 0xED4245,
        "cmds": [
            ("/kick <@user>","Kick a member"), ("/ban <@user>","Ban a member"),
            ("/unban <id>","Unban by ID"), ("/mute <@user> [dur]","Mute a member"),
            ("/unmute <@user>","Unmute a member"), ("/warn <@user>","Issue a warning"),
            ("/warnings <@user>","View warnings"), ("/clearwarns <@user>","Clear warnings"),
            ("/delwarn <id>","Delete a warning"), ("/clear [n]","Delete messages"),
            ("/slowmode [s]","Set channel slowmode"), ("/lockdown [#ch]","Lock a channel"),
            ("/unlockdown [#ch]","Unlock a channel"), ("/setuprole","Self-role panel"),
        ]
    },
    "economy": {
        "title": "🪙 Economy", "color": 0xffaa3d,
        "cmds": [
            ("/balance","Check coins"), ("/daily","Claim daily reward"),
            ("/work","Earn coins (1h cooldown)"), ("/pay <@user> <n>","Transfer coins"),
            ("/deposit <n>","Deposit to bank"), ("/withdraw <n>","Withdraw from bank"),
            ("/rob <@user>","Attempt to rob someone"), ("/slots [bet]","Slot machine"),
            ("/leaderboard","Richest members"), ("/shop","Browse item shop"),
            ("/buy <id>","Buy an item"), ("/inventory","Your items"),
            ("/eco give/take/reset","Admin: manage coins"), ("/eco additem","Add shop item"),
        ]
    },
    "leveling": {
        "title": "⭐ Leveling", "color": 0xffaa3d,
        "cmds": [
            ("/rank [@user]","View XP rank"), ("/levels","XP leaderboard"),
            ("/levelsetup","Configure XP settings"), ("/setlevelrole","Level role reward"),
            ("/removelevelrole","Remove level role"), ("/resetxp <@user>","Reset XP"),
            ("/setxp <@user> <n>","Set XP directly"),
        ]
    },
    "tickets": {
        "title": "🎫 Tickets", "color": 0x3d8bff,
        "cmds": [
            ("/ticket open","Open a ticket"), ("/ticket close","Close ticket"),
            ("/ticket claim","Claim ticket"), ("/ticket add/remove","Add/remove users"),
            ("/ticket panel","Post open button"), ("/ticket transcript","Save transcript"),
            ("/ticketsetup","Configure tickets"),
        ]
    },
    "temprooms": {
        "title": "🔊 Temp Rooms", "color": 0x3dffaa,
        "cmds": [
            ("/temproom setup","Configure temp rooms"), ("/temproom rename","Rename room"),
            ("/temproom limit","Set user limit"), ("/temproom lock/unlock","Lock/unlock"),
            ("/temproom kick/ban/unban","Manage users"), ("/temproom invite","Invite user"),
            ("/temproom transfer","Transfer ownership"), ("/temproom delete","Delete room"),
        ]
    },
    "community": {
        "title": "💬 Community", "color": 0x5865F2,
        "cmds": [
            ("/suggest <text>","Submit a suggestion"), ("/suggestion approve/deny","Decide suggestions"),
            ("/suggestsetup","Configure suggestions"), ("/automod toggle","Toggle AutoMod"),
            ("/automod spam/links/words/caps","Configure filters"), ("/alias add/remove/list","Command aliases"),
        ]
    },
    "settings": {
        "title": "⚙️ Settings", "color": 0x5865F2,
        "cmds": [
            ("/setlog [#ch]","Set mod log channel"), ("/setwelcome","Set welcome message"),
            ("/settings","View server settings"), ("/ticketsetup","Ticket system config"),
            ("/levelsetup","Leveling config"), ("/temproom setup","Temp room config"),
            ("/suggestsetup","Suggestions config"),
        ]
    },
}

class Help(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="help", description="Show all available commands grouped by category.")
    @app_commands.describe(category="Which category to show (leave empty for overview)")
    @app_commands.choices(category=[app_commands.Choice(name=v["title"], value=k) for k,v in CATEGORIES.items()])
    async def help(self, interaction: discord.Interaction, category: str = None):
        if category and category in CATEGORIES:
            cat = CATEGORIES[category]
            embed = discord.Embed(title=f"{cat['title']} Commands", color=cat["color"])
            embed.description = "\n".join(f"`{cmd}` — {desc}" for cmd,desc in cat["cmds"])
            embed.set_footer(text="[ ] = optional  < > = required  •  Type / in chat to use")
        else:
            total = sum(len(v["cmds"]) for v in CATEGORIES.values())
            embed = discord.Embed(
                title="📚 Command Help",
                description=(
                    f"**{self.bot.user.name}** — `{total}` commands across `{len(CATEGORIES)}` categories.\n\n"
                    f"Use `/help [category]` for details, or type `/` in chat for autocomplete."
                ),
                color=0x5865F2
            )
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
            for cat in CATEGORIES.values():
                sample = ", ".join(f"`{c[0].split()[0]}`" for c in cat["cmds"][:3])
                embed.add_field(name=cat["title"], value=f"{len(cat['cmds'])} commands — {sample}...", inline=True)
            embed.set_footer(text="[ ] = optional  < > = required  •  Type / in chat to use all commands")
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot): await bot.add_cog(Help(bot))
