"""
cogs/general.py
Commands: /ping  /avatar  /uptime  /botinfo  /help  /serverinfo  /membercount  /banner
"""
import discord
from discord import app_commands
from discord.ext import commands
import time
from utils import db

START_TIME = time.time()


class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /ping ─────────────────────────────────────────────────
    @app_commands.command(name="ping", description="Check the bot's latency.")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        color = 0x57F287 if latency < 100 else (0xFEE75C if latency < 200 else 0xED4245)
        emoji = "🟢" if latency < 100 else ("🟡" if latency < 200 else "🔴")
        embed = discord.Embed(title=f"{emoji} Pong!", color=color)
        embed.add_field(name="WebSocket Latency", value=f"`{latency} ms`", inline=True)
        embed.add_field(name="Status", value="`Excellent`" if latency < 100 else ("`Good`" if latency < 200 else "`Slow`"), inline=True)
        embed.set_footer(text=f"Requested by {interaction.user}", icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    # ── /avatar ───────────────────────────────────────────────
    @app_commands.command(name="avatar", description="Get a user's avatar in full size.")
    @app_commands.describe(user="User to get avatar for (default: yourself)")
    async def avatar(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        embed = discord.Embed(title=f"🖼️ {target.display_name}'s Avatar", color=0x5865F2)
        embed.set_image(url=target.display_avatar.url)
        embed.add_field(
            name="Download Links",
            value=(
                f"[PNG]({target.display_avatar.with_format('png').url})  •  "
                f"[JPG]({target.display_avatar.with_format('jpg').url})  •  "
                f"[WEBP]({target.display_avatar.with_format('webp').url})"
            )
        )
        embed.set_footer(text=f"ID: {target.id}")
        await interaction.response.send_message(embed=embed)

    # ── /banner ───────────────────────────────────────────────
    @app_commands.command(name="banner", description="Get a user's profile banner.")
    @app_commands.describe(user="User to get banner for (default: yourself)")
    async def banner(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        # Must fetch the user to get banner
        fetched = await self.bot.fetch_user(target.id)
        if not fetched.banner:
            embed = discord.Embed(
                description=f"{target.mention} doesn't have a profile banner set.",
                color=0xED4245
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        embed = discord.Embed(title=f"🎨 {target.display_name}'s Banner", color=fetched.accent_color or 0x5865F2)
        embed.set_image(url=fetched.banner.url)
        await interaction.response.send_message(embed=embed)

    # ── /uptime ───────────────────────────────────────────────
    @app_commands.command(name="uptime", description="How long the bot has been online.")
    async def uptime(self, interaction: discord.Interaction):
        elapsed = int(time.time() - START_TIME)
        days, r = divmod(elapsed, 86400)
        hours, r = divmod(r, 3600)
        minutes, seconds = divmod(r, 60)
        total_cmds = await db.get_total_commands()
        embed = discord.Embed(title="⏱️ Uptime", color=0x5DADE2)
        embed.add_field(name="Online For",     value=f"`{days}d {hours}h {minutes}m {seconds}s`", inline=False)
        embed.add_field(name="Commands Used",  value=f"`{total_cmds:,}`",                         inline=True)
        embed.add_field(name="Guilds",         value=f"`{len(self.bot.guilds)}`",                  inline=True)
        embed.add_field(name="Latency",        value=f"`{round(self.bot.latency*1000)} ms`",       inline=True)
        await interaction.response.send_message(embed=embed)

    # ── /botinfo ──────────────────────────────────────────────
    @app_commands.command(name="botinfo", description="Detailed information about this bot.")
    async def botinfo(self, interaction: discord.Interaction):
        total_users = sum(g.member_count for g in self.bot.guilds)
        total_cmds  = await db.get_total_commands()
        top_cmds    = await db.get_top_commands(5)
        elapsed     = int(time.time() - START_TIME)
        days, r     = divmod(elapsed, 86400)
        hours, r    = divmod(r, 3600)
        minutes, _  = divmod(r, 60)

        embed = discord.Embed(title="🤖 Bot Information", color=0x5865F2)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.add_field(name="Bot Name",  value=f"`{self.bot.user}`",        inline=True)
        embed.add_field(name="Bot ID",    value=f"`{self.bot.user.id}`",     inline=True)
        embed.add_field(name="Library",   value="`discord.py v2`",           inline=True)
        embed.add_field(name="Guilds",    value=f"`{len(self.bot.guilds)}`", inline=True)
        embed.add_field(name="Users",     value=f"`{total_users:,}`",        inline=True)
        embed.add_field(name="Commands",  value=f"`{total_cmds:,}` total",   inline=True)
        embed.add_field(name="Uptime",    value=f"`{days}d {hours}h {minutes}m`", inline=True)
        embed.add_field(name="Latency",   value=f"`{round(self.bot.latency*1000)} ms`", inline=True)
        if top_cmds:
            top_str = "\n".join(f"`/{c['command']}` — {c['uses']} uses" for c in top_cmds)
            embed.add_field(name="🏆 Most Used Commands", value=top_str, inline=False)
        embed.set_footer(text=f"Requested by {interaction.user}", icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    # ── /membercount ──────────────────────────────────────────
    @app_commands.command(name="membercount", description="Show the server's member count breakdown.")
    async def membercount(self, interaction: discord.Interaction):
        guild = interaction.guild
        total   = guild.member_count
        humans  = sum(1 for m in guild.members if not m.bot)
        bots    = sum(1 for m in guild.members if m.bot)
        online  = sum(1 for m in guild.members if m.status != discord.Status.offline)
        embed = discord.Embed(title=f"👥 {guild.name} — Members", color=0x57F287)
        embed.add_field(name="Total",   value=f"`{total:,}`",  inline=True)
        embed.add_field(name="Humans",  value=f"`{humans:,}`", inline=True)
        embed.add_field(name="Bots",    value=f"`{bots:,}`",   inline=True)
        embed.add_field(name="Online",  value=f"`{online:,}`", inline=True)
        embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
        await interaction.response.send_message(embed=embed)

    # ── /help ─────────────────────────────────────────────────
    @app_commands.command(name="help", description="Show all available commands grouped by category.")
    @app_commands.describe(category="Which category to show (leave empty for overview)")
    @app_commands.choices(category=[
        app_commands.Choice(name="General",    value="general"),
        app_commands.Choice(name="Moderation", value="mod"),
        app_commands.Choice(name="Economy",    value="economy"),
        app_commands.Choice(name="Leveling",   value="leveling"),
        app_commands.Choice(name="Tickets",    value="tickets"),
        app_commands.Choice(name="AutoMod",    value="automod"),
        app_commands.Choice(name="Settings",   value="settings"),
    ])
    async def help(self, interaction: discord.Interaction, category: str = None):
        categories = {
            "general": {
                "title": "🔧 General",
                "color": 0x5865F2,
                "cmds": [
                    ("/ping",         "Check bot latency"),
                    ("/avatar [@user]","View someone's avatar"),
                    ("/banner [@user]","View someone's banner"),
                    ("/uptime",        "Bot uptime & stats"),
                    ("/botinfo",       "About this bot"),
                    ("/membercount",   "Server member breakdown"),
                    ("/server",        "Server information"),
                    ("/userinfo [@user]","User details & roles"),
                    ("/roles",         "List all server roles"),
                    ("/help [cat]",    "This menu"),
                ]
            },
            "mod": {
                "title": "🛡️ Moderation",
                "color": 0xED4245,
                "cmds": [
                    ("/kick <@user>",   "Kick a member"),
                    ("/ban <@user>",    "Ban a member"),
                    ("/unban <id>",     "Unban a user by ID"),
                    ("/clear [n]",      "Delete up to 100 messages"),
                    ("/warn <@user>",   "Warn a member (auto-kick at threshold)"),
                    ("/warnings <@user>","View a member's warnings"),
                    ("/clearwarns <@user>","Clear all warnings"),
                    ("/delwarn <id>",   "Delete a specific warning"),
                    ("/setuprole",      "Create a self-role button panel"),
                    ("/panels",         "List role panels"),
                    ("/deletepanel",    "Delete a role panel"),
                ]
            },
            "economy": {
                "title": "🪙 Economy",
                "color": 0xffaa3d,
                "cmds": [
                    ("/balance [@user]","Check coin balance"),
                    ("/daily",          "Claim daily coins (24h cooldown)"),
                    ("/work",           "Earn coins (1h cooldown)"),
                    ("/pay <@user> <n>","Transfer coins to someone"),
                    ("/leaderboard",    "Top richest members"),
                    ("/shop",           "Browse the item shop"),
                    ("/buy <item_id>",  "Buy an item from the shop"),
                    ("/inventory",      "View your inventory"),
                    ("/eco give",       "Admin: give coins to user"),
                    ("/eco take",       "Admin: remove coins from user"),
                    ("/eco additem",    "Admin: add a shop item"),
                    ("/eco removeitem", "Admin: remove a shop item"),
                ]
            },
            "leveling": {
                "title": "⭐ Leveling",
                "color": 0xffaa3d,
                "cmds": [
                    ("/rank [@user]",   "View XP rank card"),
                    ("/levels",         "XP leaderboard"),
                    ("/levelsetup",     "Configure XP settings"),
                    ("/setlevelrole",   "Assign a role reward for a level"),
                    ("/removelevelrole","Remove a level role reward"),
                    ("/resetxp <@user>","Admin: reset a user's XP"),
                ]
            },
            "tickets": {
                "title": "🎫 Tickets",
                "color": 0x3d8bff,
                "cmds": [
                    ("/ticket open",    "Open a support ticket"),
                    ("/ticket close",   "Close the current ticket"),
                    ("/ticket claim",   "Claim a ticket as yours"),
                    ("/ticket add",     "Add a user to a ticket"),
                    ("/ticket remove",  "Remove a user from a ticket"),
                    ("/ticket panel",   "Post the open-ticket button"),
                    ("/ticket transcript","Save ticket chat as a file"),
                    ("/ticketsetup",    "Configure the ticket system"),
                ]
            },
            "automod": {
                "title": "🤖 AutoMod",
                "color": 0xff6b35,
                "cmds": [
                    ("/automod toggle", "Enable/disable AutoMod"),
                    ("/automod spam",   "Configure spam detection"),
                    ("/automod links",  "Configure link blocking"),
                    ("/automod words",  "Configure bad word filter"),
                    ("/automod caps",   "Configure caps filter"),
                    ("/automod mentions","Configure mass mention filter"),
                    ("/automod exempt", "Exempt a role/channel"),
                    ("/automod status", "View all AutoMod settings"),
                ]
            },
            "settings": {
                "title": "⚙️ Settings & Aliases",
                "color": 0x5865F2,
                "cmds": [
                    ("/setlog [#ch]",   "Set the moderation log channel"),
                    ("/setwelcome",     "Set welcome channel & message"),
                    ("/settings",       "View all server settings"),
                    ("/ticketsetup",    "Configure ticket system"),
                    ("/alias add",      "Add a !prefix alias for a /slash command"),
                    ("/alias remove",   "Remove an alias"),
                    ("/alias list",     "List all aliases"),
                ]
            },
        }

        if category and category in categories:
            # Single category view
            cat = categories[category]
            embed = discord.Embed(title=f"{cat['title']} Commands", color=cat["color"])
            lines = [f"`{cmd}` — {desc}" for cmd, desc in cat["cmds"]]
            embed.description = "\n".join(lines)
            embed.set_footer(text="[ ] = optional  < > = required  |  Type / to use slash commands")
        else:
            # Overview of all categories
            embed = discord.Embed(
                title="📚 Command Help",
                description=(
                    f"**{self.bot.user.name}** has `{len([c for cat in categories.values() for c in cat['cmds']])}` commands across `{len(categories)}` categories.\n\n"
                    f"Use `/help [category]` for details, or type `/` in chat for autocomplete."
                ),
                color=0x5865F2
            )
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
            for cat in categories.values():
                cmd_count = len(cat["cmds"])
                first_few = ", ".join(f"`{c[0].split()[0]}`" for c in cat["cmds"][:3])
                embed.add_field(
                    name=cat["title"],
                    value=f"{cmd_count} commands — {first_few}...",
                    inline=True
                )
            embed.set_footer(text="[ ] = optional  < > = required  |  Type / in chat to use slash commands")

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))
