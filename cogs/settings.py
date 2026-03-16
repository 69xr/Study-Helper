"""
cogs/settings.py
Commands: /setlog  /setwelcome  /settings
          /alias add  /alias remove  /alias list
Events  : on_member_join (welcome message)
          on_message     (alias handler - shows proper usage when !alias is typed)
"""
import discord
from discord import app_commands
from discord.ext import commands
from utils import db
from utils.helpers import success_embed, error_embed

# All available slash commands for alias validation
ALL_COMMANDS = [
    "ping","avatar","uptime","botinfo","help",
    "server","userinfo","roles",
    "kick","ban","unban","clear","warn","warnings","clearwarns","delwarn",
    "setuprole","panels","deletepanel",
    "setlog","setwelcome","settings",
    "ticketsetup",
    "ticket open","ticket close","ticket claim","ticket add",
    "ticket remove","ticket panel","ticket transcript",
    "balance","daily","work","pay","leaderboard","shop","buy","inventory",
    "eco give","eco take","eco reset","eco additem","eco removeitem",
    "rank","levels","levelsetup","setlevelrole","removelevelrole","resetxp",
    "automod toggle","automod spam","automod links","automod words",
    "automod caps","automod mentions","automod exempt","automod status",
    "alias add","alias remove","alias list",
    "blacklist","unblacklist","blacklistview",
    "reload","shutdown","announce","botstats","dm",
]

# Usage hints shown when a user types !alias with an args-needing command
ARG_USAGE = {
    "kick":        "/kick <@user> [reason]",
    "ban":         "/ban <@user> [reason]",
    "unban":       "/unban <user_id> [reason]",
    "warn":        "/warn <@user> [reason]",
    "clear":       "/clear [amount] [@user]",
    "warnings":    "/warnings <@user>",
    "clearwarns":  "/clearwarns <@user>",
    "delwarn":     "/delwarn <warn_id>",
    "pay":         "/pay <@user> <amount>",
    "buy":         "/buy <item_id>",
    "avatar":      "/avatar [@user]",
    "userinfo":    "/userinfo [@user]",
    "rank":        "/rank [@user]",
    "resetxp":     "/resetxp <@user>",
    "setlevelrole":"/setlevelrole <level> <@role>",
    "removelevelrole": "/removelevelrole <level>",
    "eco give":    "/eco give <@user> <amount>",
    "eco take":    "/eco take <@user> <amount>",
    "eco reset":   "/eco reset <@user>",
    "eco additem": "/eco additem <name> <price>",
    "eco removeitem": "/eco removeitem <item_id>",
    "ticket add":  "/ticket add <@user>",
    "ticket remove": "/ticket remove <@user>",
    "blacklist":   "/blacklist <user_id> [reason]",
    "unblacklist": "/unblacklist <user_id>",
    "dm":          "/dm <user_id> <message>",
    "announce":    "/announce <#channel> <title> <message>",
    "reload":      "/reload <cog|all>",
}

alias_group = app_commands.Group(name="alias", description="Manage command aliases for this server.")


class Settings(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ══════════════════════════════════════════════════════════
    #  SERVER SETTINGS
    # ══════════════════════════════════════════════════════════

    @app_commands.command(name="setlog", description="Set the moderation log channel.")
    @app_commands.describe(channel="Channel for mod logs (leave empty to disable)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setlog(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        await db.set_guild_setting(interaction.guild_id, "log_channel", channel.id if channel else None)
        if channel:
            await interaction.response.send_message(
                embed=success_embed("Log Channel Set", f"Mod logs will be sent to {channel.mention}."),
                ephemeral=True)
        else:
            await interaction.response.send_message(
                embed=success_embed("Log Channel Disabled", "Mod logging has been turned off."),
                ephemeral=True)

    @app_commands.command(name="setwelcome", description="Set the welcome channel and message.")
    @app_commands.describe(
        channel="Channel to post welcome messages in",
        message="Template: use {user}, {server}, {count}"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setwelcome(self, interaction: discord.Interaction,
                          channel: discord.TextChannel,
                          message: str = "Welcome {user} to **{server}**! You are member #{count}."):
        await db.set_guild_setting(interaction.guild_id, "welcome_channel", channel.id)
        await db.set_guild_setting(interaction.guild_id, "welcome_msg", message)
        preview = (message
            .replace("{user}",   interaction.user.mention)
            .replace("{server}", interaction.guild.name)
            .replace("{count}",  str(interaction.guild.member_count)))
        embed = success_embed("Welcome Set", f"Welcome messages → {channel.mention}")
        embed.add_field(name="Preview", value=preview, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="settings", description="View current bot settings.")
    @app_commands.checks.has_permissions(administrator=True)
    async def settings_cmd(self, interaction: discord.Interaction):
        s  = await db.get_guild_settings(interaction.guild_id)
        ts = await db.get_ticket_settings(interaction.guild_id)
        log_ch     = interaction.guild.get_channel(s["log_channel"])     if s and s.get("log_channel")     else None
        welcome_ch = interaction.guild.get_channel(s["welcome_channel"]) if s and s.get("welcome_channel") else None
        mute_role  = interaction.guild.get_role(s["mute_role"])          if s and s.get("mute_role")       else None
        embed = discord.Embed(title=f"⚙️ Settings — {interaction.guild.name}", color=0x5865F2)
        embed.add_field(name="📋 Log Channel",      value=log_ch.mention if log_ch else "`not set`",         inline=True)
        embed.add_field(name="👋 Welcome Channel",  value=welcome_ch.mention if welcome_ch else "`not set`", inline=True)
        embed.add_field(name="🔇 Mute Role",        value=mute_role.mention if mute_role else "`not set`",   inline=True)
        embed.add_field(name="💬 Welcome Message",  value=f"`{s.get('welcome_msg','not set')}`" if s else "`not set`", inline=False)
        embed.add_field(name="🎫 Ticket Category",  value=f"`{ts.get('category_id','not set')}`",  inline=True)
        embed.add_field(name="🎫 Support Role",     value=f"`{ts.get('support_role','not set')}`", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ══════════════════════════════════════════════════════════
    #  ALIAS COMMANDS
    # ══════════════════════════════════════════════════════════

    @alias_group.command(name="add", description="Add a prefix alias for a slash command.")
    @app_commands.describe(
        alias="Shortcut to type (e.g. bal, r, lb)",
        command="Slash command it maps to (e.g. balance, rank, leaderboard)"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def alias_add(self, interaction: discord.Interaction, alias: str, command: str):
        alias   = alias.lower().strip().lstrip("!/")
        command = command.lower().strip().lstrip("/")
        if " " in alias or len(alias) > 30:
            await interaction.response.send_message(
                embed=error_embed("Invalid Alias", "Alias must be one word, max 30 chars, no spaces."),
                ephemeral=True)
            return
        if command not in ALL_COMMANDS:
            matches = [c for c in ALL_COMMANDS if c.startswith(command)]
            if not matches:
                await interaction.response.send_message(
                    embed=error_embed("Unknown Command",
                        f"`/{command}` is not a known bot command.\n"
                        f"Use `/alias list` to see available commands or try `/alias add {alias} balance`."),
                    ephemeral=True)
                return
            command = matches[0]
        await db.set_alias(interaction.guild_id, alias, command)
        await interaction.response.send_message(
            embed=success_embed("Alias Added",
                f"`!{alias}` → `/{command}`\n"
                f"Members can now type `!{alias}` and the bot will show them how to run `/{command}`."),
            ephemeral=True)

    @alias_group.command(name="remove", description="Remove a prefix alias.")
    @app_commands.describe(alias="The alias to remove")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def alias_remove(self, interaction: discord.Interaction, alias: str):
        removed = await db.delete_alias(interaction.guild_id, alias.lower().lstrip("!/"))
        if not removed:
            await interaction.response.send_message(
                embed=error_embed("Not Found", f"No alias `{alias}` in this server."),
                ephemeral=True)
            return
        await interaction.response.send_message(
            embed=success_embed("Removed", f"Alias `!{alias}` deleted."), ephemeral=True)

    @alias_group.command(name="list", description="View all command aliases for this server.")
    async def alias_list(self, interaction: discord.Interaction):
        aliases = await db.get_aliases(interaction.guild_id)
        embed = discord.Embed(title=f"⚡ Aliases — {interaction.guild.name}", color=0x3d8bff)
        if not aliases:
            embed.description = (
                "No aliases yet.\n\n"
                "**Example:** `/alias add r rank` — then type `!r` and the bot shows you how to run `/rank`\n"
                "**Example:** `/alias add bal balance`"
            )
        else:
            lines = [f"`!{a['alias']}` → `/{a['command']}`" for a in aliases]
            embed.description = "\n".join(lines)
            embed.set_footer(text=f"{len(aliases)} alias(es) • Trigger with ! prefix")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ══════════════════════════════════════════════════════════
    #  ON_MESSAGE — alias handler
    # ══════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        content = message.content.strip()
        if not content.startswith("!"):
            return
        parts = content[1:].split()
        if not parts:
            return
        alias     = parts[0].lower()
        user_args = parts[1:]  # args typed after the alias

        command_name = await db.get_alias_command(message.guild.id, alias)
        if not command_name:
            return

        # Blacklist check
        bl = await db.is_blacklisted(message.author.id)
        if bl:
            try:
                await message.reply(
                    "🚫 You are blacklisted from using this bot.",
                    mention_author=False, delete_after=5)
            except Exception:
                pass
            return

        # Build the response embed
        if command_name in ARG_USAGE:
            usage = ARG_USAGE[command_name]
            args_str = " ".join(user_args)
            lines = [
                f"⚡ **`!{alias}`** maps to **`/{command_name}`**",
                f"",
                f"**Usage:** `{usage}`",
            ]
            if args_str:
                lines.append(f"**Your input:** `{args_str}`")
            lines.append(f"")
            lines.append(f"Type `/{command_name.split()[0]}` in Discord to get the full slash command with autocomplete!")
            desc = "\n".join(lines)
        else:
            # No-arg command — just show the slash command clearly
            desc = (
                f"⚡ **`!{alias}`** maps to **`/{command_name}`**\n\n"
                f"Type **`/{command_name}`** in the chat box to run it instantly with Discord's slash command interface!"
            )

        embed = discord.Embed(description=desc, color=0x3d8bff)
        embed.set_footer(text="Type / in chat to see all available commands with autocomplete")
        try:
            await message.reply(embed=embed, mention_author=False, delete_after=20)
        except discord.Forbidden:
            pass

    # ══════════════════════════════════════════════════════════
    #  ON_MEMBER_JOIN — welcome message
    # ══════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        s = await db.get_guild_settings(member.guild.id)
        if not s or not s.get("welcome_channel"):
            return
        ch = member.guild.get_channel(s["welcome_channel"])
        if not ch:
            return
        msg = s.get("welcome_msg", "Welcome {user} to **{server}**!")
        msg = (msg
               .replace("{user}",   member.mention)
               .replace("{server}", member.guild.name)
               .replace("{count}",  str(member.guild.member_count)))
        embed = discord.Embed(title="👋 Welcome!", description=msg, color=0x57F287)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Member #{member.guild.member_count}")
        try:
            await ch.send(embed=embed)
        except discord.Forbidden:
            pass

    # ══════════════════════════════════════════════════════════
    #  ERROR HANDLER
    # ══════════════════════════════════════════════════════════

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=error_embed("Missing Permissions", "You need **Administrator** for this command."),
                    ephemeral=True)


async def setup(bot: commands.Bot):
    bot.tree.add_command(alias_group)
    await bot.add_cog(Settings(bot))
