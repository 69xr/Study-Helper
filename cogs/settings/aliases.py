"""
cogs/settings/aliases.py
Aliases intercept messages and ACTUALLY EXECUTE the slash command callback directly.
No prefix needed — just type the alias word and the command runs.
Prefix ! also works for muscle memory.
"""
import discord, inspect, asyncio
from discord import app_commands
from discord.ext import commands
from utils import db
from utils.helpers import success_embed, error_embed


# ══════════════════════════════════════════════════════════
#  SYNTHETIC INTERACTION
#  Wraps a discord.Message so slash command callbacks can be
#  called directly — responses go to the same channel.
# ══════════════════════════════════════════════════════════

class _SyntheticResponse:
    def __init__(self, interaction):
        self._ix   = interaction
        self._done = False

    def is_done(self): return self._done

    async def send_message(self, content=None, *, embed=None, embeds=None,
                           ephemeral=False, view=None, delete_after=None, **kw):
        self._done = True
        try:
            msg = await self._ix.channel.send(
                content=content, embed=embed,
                embeds=embeds,   view=view)
            if delete_after:
                asyncio.get_event_loop().call_later(
                    delete_after, lambda: asyncio.ensure_future(msg.delete()))
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def defer(self, ephemeral=False, thinking=False):
        self._done = True

    async def edit_message(self, **kw):
        pass


class _SyntheticFollowup:
    def __init__(self, interaction):
        self._ix = interaction

    async def send(self, content=None, *, embed=None, embeds=None,
                   ephemeral=False, view=None, delete_after=None, **kw):
        try:
            msg = await self._ix.channel.send(
                content=content, embed=embed, embeds=embeds, view=view)
            if delete_after:
                asyncio.get_event_loop().call_later(
                    delete_after, lambda: asyncio.ensure_future(msg.delete()))
            return msg
        except (discord.Forbidden, discord.HTTPException):
            pass


class SyntheticInteraction:
    """Minimal discord.Interaction shim built from a Message."""
    def __init__(self, bot, message: discord.Message):
        self._bot      = bot
        self._message  = message
        # Attributes commands read
        self.user      = message.author
        self.member    = message.author
        self.guild     = message.guild
        self.guild_id  = message.guild.id if message.guild else None
        self.channel   = message.channel
        self.channel_id= message.channel.id
        self.extras    = {}
        self.client    = bot
        self.locale    = None
        self.guild_locale = None
        self.response  = _SyntheticResponse(self)
        self.followup  = _SyntheticFollowup(self)

    @property
    def permissions(self):
        if isinstance(self.user, discord.Member):
            return self.user.guild_permissions
        return discord.Permissions.none()


# ══════════════════════════════════════════════════════════
#  ALIAS GROUP COMMANDS
# ══════════════════════════════════════════════════════════

ALL_COMMANDS = [
    # General
    "ping", "avatar", "banner", "uptime", "botinfo", "help",
    "server", "servericon", "serverbanner", "membercount",
    "userinfo", "roleinfo", "emojiinfo", "snipe",
    "remind", "reminders", "remindcancel", "afk",
    # Moderation
    "kick", "ban", "unban", "mute", "unmute", "setupmute",
    "timeout", "untimeout",
    "warn", "warnings", "clearwarns", "delwarn",
    "clear", "slowmode", "lockdown", "unlockdown",
    "note add", "note view", "note delete",
    "warnthreshold set", "warnthreshold list", "warnthreshold remove",
    # Roles
    "panels", "autorole add", "autorole remove", "autorole list",
    # Settings
    "setlog", "setwelcome", "settings",
    # Temp Rooms
    "temproom setup", "temproom rename", "temproom limit",
    "temproom lock", "temproom unlock", "temproom kick",
    "temproom ban", "temproom unban", "temproom transfer",
    "temproom delete", "temproom invite", "temproom info",
    # Music
    "play", "pause", "resume", "skip", "stop", "queue",
    "nowplaying", "volume", "loop", "shuffle", "remove", "join", "leave", "clearqueue",
    # Community / AutoMod
    "automod toggle", "automod spam", "automod links", "automod words",
    "automod caps", "automod mentions", "automod exempt", "automod status",
    "alias add", "alias remove", "alias list",
    # Security
    "lockserver", "unlockserver", "antiraid", "verification",
    # Owner
    "blacklist", "unblacklist", "blacklistview",
    "reload", "shutdown", "announce", "botstats", "dm",
]

alias_group = app_commands.Group(name="alias", description="Manage command aliases for this server.")


class Aliases(commands.Cog):
    def __init__(self, bot): self.bot = bot

    # ── /alias add ────────────────────────────────────────
    @alias_group.command(name="add", description="Add an alias for a slash command.")
    @app_commands.describe(
        alias="Word to type (e.g. a, r, bal) — no prefix needed",
        command="Slash command it runs (e.g. avatar, rank, balance)"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def alias_add(self, interaction: discord.Interaction, alias: str, command: str):
        alias   = alias.lower().strip().lstrip("!/")
        command = command.lower().strip().lstrip("/")
        if " " in alias or len(alias) > 30:
            await interaction.response.send_message(
                embed=error_embed("Invalid", "Alias must be one word, max 30 chars."), ephemeral=True)
            return
        if command not in ALL_COMMANDS:
            matches = [c for c in ALL_COMMANDS if c.startswith(command)]
            if not matches:
                await interaction.response.send_message(
                    embed=error_embed("Unknown Command",
                        f"`/{command}` not found.\nUse `/alias list` to see all commands."),
                    ephemeral=True)
                return
            command = matches[0]
        await db.set_alias(interaction.guild_id, alias, command)
        await interaction.response.send_message(
            embed=success_embed("Alias Added",
                f"Type **`{alias}`** in any channel and `/{command}` runs instantly."),
            ephemeral=True)

    # ── /alias remove ──────────────────────────────────────
    @alias_group.command(name="remove", description="Remove an alias.")
    @app_commands.describe(alias="Alias to remove")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def alias_remove(self, interaction: discord.Interaction, alias: str):
        removed = await db.delete_alias(interaction.guild_id, alias.lower().lstrip("!/"))
        if not removed:
            await interaction.response.send_message(
                embed=error_embed("Not Found", f"No alias `{alias}`."), ephemeral=True)
            return
        await interaction.response.send_message(
            embed=success_embed("Removed", f"Alias `{alias}` deleted."), ephemeral=True)

    # ── /alias list ───────────────────────────────────────
    @alias_group.command(name="list", description="List all command aliases.")
    async def alias_list(self, interaction: discord.Interaction):
        aliases = await db.get_aliases(interaction.guild_id)
        embed   = discord.Embed(title=f"⚡ Aliases — {interaction.guild.name}", color=0x3d8bff)
        if not aliases:
            embed.description = (
                "No aliases yet.\n\n"
                "**Example:** `/alias add a avatar` — then just type `a` in chat to run `/avatar`\n"
                "**Example:** `/alias add r rank` — type `r` to check your XP rank"
            )
        else:
            lines = [f"`{a['alias']}` → `/{a['command']}`" for a in aliases]
            embed.description = "\n".join(lines)
            embed.set_footer(text=f"{len(aliases)} alias(es) • Just type the alias word in chat — no prefix needed")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ══════════════════════════════════════════════════════
    #  ON_MESSAGE — actually runs the command
    # ══════════════════════════════════════════════════════

    def _find_command(self, command_name: str):
        """Find an app command by name — searches tree AND all cog commands."""
        parts = command_name.split()
        bot   = self.bot

        if len(parts) == 1:
            # Try tree first
            cmd = bot.tree.get_command(parts[0])
            if cmd: return cmd
            # Search all cogs (catches @app_commands.command inside Cog classes)
            for cog in bot.cogs.values():
                for app_cmd in cog.get_app_commands():
                    if app_cmd.name == parts[0]:
                        return app_cmd

        elif len(parts) == 2:
            # Group command (e.g. "eco give", "ticket open")
            grp = bot.tree.get_command(parts[0])
            if grp and hasattr(grp, "get_command"):
                sub = grp.get_command(parts[1])
                if sub: return sub
            # Search cog groups
            for cog in bot.cogs.values():
                for app_cmd in cog.get_app_commands():
                    if app_cmd.name == parts[0] and hasattr(app_cmd, "get_command"):
                        sub = app_cmd.get_command(parts[1])
                        if sub: return sub

        return None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild: return
        content = message.content.strip()
        if not content: return

        parts     = content.split()
        # Strip any leading prefix characters (!, /, .) so "!a" → "a", "/a" → "a"
        alias     = parts[0].lstrip("!/." ).lower()
        user_args = parts[1:]

        if not alias:
            return

        # Only act if this word is a registered alias — checked against DB first
        # so normal chat messages are NEVER intercepted
        command_name = await db.get_alias_command(message.guild.id, alias)
        if not command_name: return

        # Blacklist check
        bl = await db.is_blacklisted(message.author.id)
        if bl:
            try:
                await message.reply("🚫 You are blacklisted.", mention_author=False, delete_after=5)
            except Exception:
                pass
            return

        # Delete the trigger message to keep chat clean
        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass

        # Find the app command — search tree AND all loaded cogs
        # (bot.tree.get_command can miss cog-bound commands)
        app_cmd = self._find_command(command_name)

        if app_cmd is None:
            try:
                await message.channel.send(
                    f"{message.author.mention} ⚡ Alias `{alias}` → `/{command_name}` "
                    f"— command not found in tree.",
                    delete_after=8)
            except discord.Forbidden:
                pass
            return

        # Build synthetic interaction
        interaction = SyntheticInteraction(self.bot, message)

        # Get the raw callback function and its binding (cog instance)
        callback = app_cmd.callback
        binding  = getattr(app_cmd, "binding", None)

        # Parse user_args into typed kwargs if any args given
        kwargs = {}
        if user_args:
            try:
                sig    = inspect.signature(callback)
                params = [
                    (name, p) for name, p in sig.parameters.items()
                    if name not in ("self", "interaction")
                ]
                for i, (param_name, param) in enumerate(params):
                    if i >= len(user_args): break
                    raw = user_args[i]
                    ann = param.annotation
                    try:
                        if ann is discord.Member or (
                            hasattr(ann, "__args__") and discord.Member in ann.__args__
                        ):
                            uid = int(raw.strip("<@!>"))
                            member = message.guild.get_member(uid)
                            if member:
                                kwargs[param_name] = member
                        elif ann is int:
                            kwargs[param_name] = int(raw)
                        else:
                            kwargs[param_name] = raw
                    except Exception:
                        kwargs[param_name] = raw
            except Exception:
                pass  # call with no extra args if parsing fails

        # Actually invoke the command
        try:
            if binding:
                await callback(binding, interaction, **kwargs)
            else:
                await callback(interaction, **kwargs)
        except Exception as e:
            try:
                await message.channel.send(
                    f"{message.author.mention} ⚡ `/{command_name}` → `{type(e).__name__}: {e}`",
                    delete_after=10)
            except discord.Forbidden:
                pass


async def setup(bot):
    bot.tree.add_command(alias_group)
    await bot.add_cog(Aliases(bot))
