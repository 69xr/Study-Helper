"""
cogs/automod.py
Features : Spam detection, link blocking, bad word filter, caps filter, mass mention filter
Commands : /automod  (unified setup command with subcommands)
Events   : on_message
"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone, timedelta
from collections import defaultdict, deque
import re
import json
from utils import db
from utils.helpers import error_embed, success_embed, send_log

# ── URL regex ─────────────────────────────────────────────────
URL_RE = re.compile(
    r"(?:https?://|www\.)[^\s]+|discord\.gg/[^\s]+",
    re.IGNORECASE
)

automod_group = app_commands.Group(name="automod", description="Auto-moderation settings.")


class SpamTracker:
    """Tracks message timestamps per (guild, user) for spam detection."""
    def __init__(self):
        self._msgs: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=20))

    def add(self, guild_id: int, user_id: int) -> list[datetime]:
        key = (guild_id, user_id)
        self._msgs[key].append(datetime.now(timezone.utc))
        return list(self._msgs[key])

    def clear(self, guild_id: int, user_id: int):
        self._msgs.pop((guild_id, user_id), None)


class AutoMod(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot    = bot
        self.spam   = SpamTracker()

    # ════════════════════════════════════════════════
    #  CORE EVENT
    # ════════════════════════════════════════════════
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild: return
        if not isinstance(message.author, discord.Member): return

        settings = await db.get_automod_settings(message.guild.id)
        if not settings["enabled"]: return

        # Exempt roles
        exempt_roles = json.loads(settings["exempt_roles"] or "[]")
        if any(r.id in exempt_roles for r in message.author.roles): return

        # Exempt channels
        exempt_channels = json.loads(settings["exempt_channels"] or "[]")
        if message.channel.id in exempt_channels: return

        # Run each check — first hit wins and returns
        if settings["spam_enabled"]    and await self._check_spam(message, settings):    return
        if settings["links_enabled"]   and await self._check_links(message, settings):   return
        if settings["words_enabled"]   and await self._check_words(message, settings):   return
        if settings["caps_enabled"]    and await self._check_caps(message, settings):     return
        if settings["mention_enabled"] and await self._check_mentions(message, settings): return

    # ── SPAM ─────────────────────────────────────────────────
    async def _check_spam(self, message: discord.Message, settings: dict) -> bool:
        timestamps = self.spam.add(message.guild.id, message.author.id)
        window     = timedelta(seconds=settings["spam_window"])
        threshold  = settings["spam_threshold"]

        recent = [t for t in timestamps if (datetime.now(timezone.utc) - t) <= window]
        if len(recent) < threshold:
            return False

        self.spam.clear(message.guild.id, message.author.id)
        # Delete recent messages
        try:
            def is_spam(m): return m.author.id == message.author.id
            await message.channel.purge(limit=threshold + 2, check=is_spam, reason="AutoMod: spam")
        except discord.Forbidden:
            pass

        await self._take_action(message, settings["spam_action"], "SPAM",
                                 f"{len(recent)} messages in {settings['spam_window']}s")
        return True

    # ── LINKS ─────────────────────────────────────────────────
    async def _check_links(self, message: discord.Message, settings: dict) -> bool:
        if not URL_RE.search(message.content): return False

        whitelist = json.loads(settings["links_whitelist"] or "[]")
        for domain in whitelist:
            if domain.lower() in message.content.lower():
                return False

        if settings["links_action"] == "delete":
            try: await message.delete()
            except: pass
            try:
                await message.channel.send(
                    embed=error_embed("Link Blocked", f"{message.author.mention}, links are not allowed here."),
                    delete_after=5
                )
            except: pass
            await db.log_automod(message.guild.id, message.author.id, "LINKS", "delete", message.content[:100])
            return True

        await self._take_action(message, settings["links_action"], "LINKS", "sent a link")
        return True

    # ── BAD WORDS ─────────────────────────────────────────────
    async def _check_words(self, message: discord.Message, settings: dict) -> bool:
        bad_words = json.loads(settings["bad_words"] or "[]")
        if not bad_words: return False

        content_lower = message.content.lower()
        matched = next((w for w in bad_words if w.lower() in content_lower), None)
        if not matched: return False

        if settings["words_action"] == "delete":
            try: await message.delete()
            except: pass
            try:
                await message.channel.send(
                    embed=error_embed("Message Removed", f"{message.author.mention}, that word is not allowed."),
                    delete_after=5
                )
            except: pass
            await db.log_automod(message.guild.id, message.author.id, "WORDS", "delete", matched)
            return True

        await self._take_action(message, settings["words_action"], "WORDS", f"used blocked word: {matched}")
        return True

    # ── CAPS ─────────────────────────────────────────────────
    async def _check_caps(self, message: discord.Message, settings: dict) -> bool:
        text = message.content
        if len(text) < settings["caps_min_length"]: return False

        letters = [c for c in text if c.isalpha()]
        if not letters: return False

        caps_pct = sum(1 for c in letters if c.isupper()) / len(letters) * 100
        if caps_pct < settings["caps_threshold"]: return False

        if settings["caps_action"] == "delete":
            try: await message.delete()
            except: pass
            try:
                await message.channel.send(
                    embed=error_embed("Caps Limit", f"{message.author.mention}, please avoid excessive caps."),
                    delete_after=5
                )
            except: pass
            await db.log_automod(message.guild.id, message.author.id, "CAPS", "delete", f"{caps_pct:.0f}%")
            return True

        await self._take_action(message, settings["caps_action"], "CAPS", f"{caps_pct:.0f}% caps")
        return True

    # ── MENTIONS ─────────────────────────────────────────────
    async def _check_mentions(self, message: discord.Message, settings: dict) -> bool:
        mention_count = len(message.mentions) + len(message.role_mentions)
        if mention_count < settings["mention_threshold"]: return False

        try: await message.delete()
        except: pass

        await self._take_action(message, settings["mention_action"], "MENTIONS",
                                 f"{mention_count} mentions in one message")
        return True

    # ── ACTION DISPATCHER ────────────────────────────────────
    async def _take_action(self, message: discord.Message, action: str, rule: str, detail: str):
        member  = message.author
        guild   = message.guild
        channel = message.channel
        reason  = f"AutoMod [{rule}]: {detail}"

        # Always delete the triggering message
        try: await message.delete()
        except: pass

        warn_embed = error_embed(f"AutoMod — {rule}", f"{member.mention}, {detail}.")

        if action == "warn":
            total = await db.add_warning(guild.id, member.id, self.bot.user.id, reason)
            warn_embed.set_footer(text=f"Warning #{total}")
            try: await channel.send(embed=warn_embed, delete_after=8)
            except: pass

        elif action == "mute":
            guild_settings = await db.get_guild_settings(guild.id)
            mute_role_id   = guild_settings.get("mute_role") if guild_settings else None
            mute_role      = guild.get_role(mute_role_id) if mute_role_id else None
            if mute_role:
                try:
                    await member.add_roles(mute_role, reason=reason)
                    try: await channel.send(embed=warn_embed, delete_after=8)
                    except: pass
                    # Auto-unmute after 5 minutes
                    import asyncio
                    async def unmute():
                        await asyncio.sleep(300)
                        try: await member.remove_roles(mute_role, reason="AutoMod: mute expired")
                        except: pass
                    self.bot.loop.create_task(unmute())
                except discord.Forbidden:
                    pass
            else:
                # Fallback to warn if no mute role
                await db.add_warning(guild.id, member.id, self.bot.user.id, reason)
                try: await channel.send(embed=warn_embed, delete_after=8)
                except: pass

        elif action == "kick":
            try:
                await member.send(embed=error_embed(f"Kicked from {guild.name}", reason))
            except: pass
            try: await member.kick(reason=reason)
            except: pass

        elif action == "ban":
            try:
                await member.send(embed=error_embed(f"Banned from {guild.name}", reason))
            except: pass
            try: await member.ban(reason=reason, delete_message_days=0)
            except: pass

        # Log to DB + log channel
        await db.log_automod(guild.id, member.id, rule, action, detail)

        g_settings = await db.get_guild_settings(guild.id)
        log_ch_id  = g_settings.get("log_channel") if g_settings else None
        if log_ch_id:
            log_embed = discord.Embed(title=f"🤖 AutoMod — {rule}", color=0xffaa3d)
            log_embed.add_field(name="User",   value=f"{member.mention} `{member}`", inline=True)
            log_embed.add_field(name="Action", value=action.upper(),                  inline=True)
            log_embed.add_field(name="Detail", value=detail,                          inline=False)
            log_embed.set_footer(text=f"Channel: #{channel.name}")
            await send_log(guild, log_ch_id, log_embed)

    # ════════════════════════════════════════════════
    #  SLASH COMMANDS
    # ════════════════════════════════════════════════

    @automod_group.command(name="toggle", description="Enable or disable AutoMod.")
    @app_commands.describe(enabled="Turn AutoMod on or off")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def toggle(self, interaction: discord.Interaction, enabled: bool):
        await db.set_automod_setting(interaction.guild_id, "enabled", int(enabled))
        await interaction.response.send_message(
            embed=success_embed("AutoMod " + ("Enabled ✅" if enabled else "Disabled ❌")),
            ephemeral=True
        )

    @automod_group.command(name="spam", description="Configure spam detection.")
    @app_commands.describe(
        enabled="Enable spam filter",
        threshold="Messages in window to trigger",
        window="Time window in seconds",
        action="Action to take: warn | mute | kick | ban"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def spam_cmd(self, interaction: discord.Interaction,
                       enabled: bool = None,
                       threshold: app_commands.Range[int, 2, 20] = None,
                       window:    app_commands.Range[int, 2, 60]  = None,
                       action: str = None):
        if enabled is not None:   await db.set_automod_setting(interaction.guild_id, "spam_enabled",    int(enabled))
        if threshold is not None: await db.set_automod_setting(interaction.guild_id, "spam_threshold",  threshold)
        if window is not None:    await db.set_automod_setting(interaction.guild_id, "spam_window",     window)
        if action in ("warn","mute","kick","ban"):
            await db.set_automod_setting(interaction.guild_id, "spam_action", action)
        s = await db.get_automod_settings(interaction.guild_id)
        embed = success_embed("Spam Filter Updated")
        embed.add_field(name="Status",    value="✅" if s["spam_enabled"] else "❌", inline=True)
        embed.add_field(name="Threshold", value=f"{s['spam_threshold']} msgs / {s['spam_window']}s", inline=True)
        embed.add_field(name="Action",    value=s["spam_action"].upper(), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @automod_group.command(name="links", description="Configure link blocking.")
    @app_commands.describe(
        enabled="Enable link filter",
        action="Action: delete | warn | mute | kick | ban",
        whitelist="Comma-separated allowed domains (e.g. youtube.com,twitch.tv)"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def links_cmd(self, interaction: discord.Interaction,
                        enabled: bool = None, action: str = None, whitelist: str = None):
        if enabled is not None: await db.set_automod_setting(interaction.guild_id, "links_enabled", int(enabled))
        if action in ("delete","warn","mute","kick","ban"):
            await db.set_automod_setting(interaction.guild_id, "links_action", action)
        if whitelist is not None:
            domains = [d.strip() for d in whitelist.split(",") if d.strip()]
            await db.set_automod_setting(interaction.guild_id, "links_whitelist", json.dumps(domains))
        s = await db.get_automod_settings(interaction.guild_id)
        wl = json.loads(s["links_whitelist"] or "[]")
        embed = success_embed("Link Filter Updated")
        embed.add_field(name="Status",    value="✅" if s["links_enabled"] else "❌", inline=True)
        embed.add_field(name="Action",    value=s["links_action"].upper(),             inline=True)
        embed.add_field(name="Whitelist", value=", ".join(wl) or "None",              inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @automod_group.command(name="words", description="Configure bad word filter.")
    @app_commands.describe(
        enabled="Enable word filter",
        add_words="Comma-separated words to block",
        remove_words="Comma-separated words to unblock",
        action="Action: delete | warn | mute | kick | ban"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def words_cmd(self, interaction: discord.Interaction,
                        enabled: bool = None, add_words: str = None,
                        remove_words: str = None, action: str = None):
        if enabled is not None: await db.set_automod_setting(interaction.guild_id, "words_enabled", int(enabled))
        if action in ("delete","warn","mute","kick","ban"):
            await db.set_automod_setting(interaction.guild_id, "words_action", action)

        s = await db.get_automod_settings(interaction.guild_id)
        current = json.loads(s["bad_words"] or "[]")

        if add_words:
            new = [w.strip().lower() for w in add_words.split(",") if w.strip()]
            current = list(set(current + new))
        if remove_words:
            rem = [w.strip().lower() for w in remove_words.split(",")]
            current = [w for w in current if w not in rem]

        await db.set_automod_setting(interaction.guild_id, "bad_words", json.dumps(current))

        s = await db.get_automod_settings(interaction.guild_id)
        embed = success_embed("Word Filter Updated")
        embed.add_field(name="Status",     value="✅" if s["words_enabled"] else "❌", inline=True)
        embed.add_field(name="Action",     value=s["words_action"].upper(),             inline=True)
        embed.add_field(name="Word Count", value=str(len(current)),                     inline=True)
        embed.add_field(name="Words",
            value=", ".join(f"`{w}`" for w in current[:20]) + ("..." if len(current) > 20 else "") or "None",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @automod_group.command(name="caps", description="Configure caps filter.")
    @app_commands.describe(
        enabled="Enable caps filter",
        threshold="Percentage of caps to trigger (0-100)",
        min_length="Minimum message length to check",
        action="Action: delete | warn | mute"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def caps_cmd(self, interaction: discord.Interaction,
                       enabled: bool = None,
                       threshold:   app_commands.Range[int, 10, 100] = None,
                       min_length:  app_commands.Range[int, 5, 200]  = None,
                       action: str = None):
        if enabled is not None:    await db.set_automod_setting(interaction.guild_id, "caps_enabled",    int(enabled))
        if threshold is not None:  await db.set_automod_setting(interaction.guild_id, "caps_threshold",  threshold)
        if min_length is not None: await db.set_automod_setting(interaction.guild_id, "caps_min_length", min_length)
        if action in ("delete","warn","mute"):
            await db.set_automod_setting(interaction.guild_id, "caps_action", action)
        s = await db.get_automod_settings(interaction.guild_id)
        embed = success_embed("Caps Filter Updated")
        embed.add_field(name="Status",     value="✅" if s["caps_enabled"] else "❌",    inline=True)
        embed.add_field(name="Threshold",  value=f"{s['caps_threshold']}%",              inline=True)
        embed.add_field(name="Min Length", value=f"{s['caps_min_length']} chars",        inline=True)
        embed.add_field(name="Action",     value=s["caps_action"].upper(),               inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @automod_group.command(name="mentions", description="Configure mass mention filter.")
    @app_commands.describe(
        enabled="Enable mention filter",
        threshold="Number of mentions to trigger",
        action="Action: delete | warn | mute | kick | ban"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def mentions_cmd(self, interaction: discord.Interaction,
                           enabled: bool = None,
                           threshold: app_commands.Range[int, 2, 30] = None,
                           action: str = None):
        if enabled is not None:    await db.set_automod_setting(interaction.guild_id, "mention_enabled",   int(enabled))
        if threshold is not None:  await db.set_automod_setting(interaction.guild_id, "mention_threshold", threshold)
        if action in ("delete","warn","mute","kick","ban"):
            await db.set_automod_setting(interaction.guild_id, "mention_action", action)
        s = await db.get_automod_settings(interaction.guild_id)
        embed = success_embed("Mention Filter Updated")
        embed.add_field(name="Status",    value="✅" if s["mention_enabled"] else "❌", inline=True)
        embed.add_field(name="Threshold", value=f"{s['mention_threshold']} mentions",   inline=True)
        embed.add_field(name="Action",    value=s["mention_action"].upper(),            inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @automod_group.command(name="exempt", description="Exempt a role or channel from AutoMod.")
    @app_commands.describe(
        role="Role to exempt (leave empty if setting channel)",
        channel="Channel to exempt (leave empty if setting role)",
        remove="Remove from exemption list instead of adding"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def exempt(self, interaction: discord.Interaction,
                     role: discord.Role = None, channel: discord.TextChannel = None,
                     remove: bool = False):
        s = await db.get_automod_settings(interaction.guild_id)
        exempt_roles    = json.loads(s["exempt_roles"]    or "[]")
        exempt_channels = json.loads(s["exempt_channels"] or "[]")

        if role:
            if remove: exempt_roles    = [r for r in exempt_roles    if r != role.id]
            else:      exempt_roles.append(role.id)
            await db.set_automod_setting(interaction.guild_id, "exempt_roles", json.dumps(list(set(exempt_roles))))

        if channel:
            if remove: exempt_channels = [c for c in exempt_channels if c != channel.id]
            else:      exempt_channels.append(channel.id)
            await db.set_automod_setting(interaction.guild_id, "exempt_channels", json.dumps(list(set(exempt_channels))))

        await interaction.response.send_message(
            embed=success_embed("Exemption Updated",
                f"{'Removed' if remove else 'Added'} exemption for "
                f"{role.mention if role else ''}{channel.mention if channel else ''}."),
            ephemeral=True
        )

    @automod_group.command(name="status", description="View all AutoMod settings at once.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction):
        s   = await db.get_automod_settings(interaction.guild_id)
        wl  = json.loads(s["links_whitelist"] or "[]")
        bw  = json.loads(s["bad_words"]       or "[]")
        er  = json.loads(s["exempt_roles"]    or "[]")
        ec  = json.loads(s["exempt_channels"] or "[]")

        embed = discord.Embed(
            title="🤖 AutoMod Status",
            color=0x3d8bff if s["enabled"] else 0xff3d5a
        )
        embed.add_field(name="Master Switch", value="✅ ON" if s["enabled"] else "❌ OFF", inline=False)
        embed.add_field(name="🔁 Spam",
            value=f"{'✅' if s['spam_enabled'] else '❌'} {s['spam_threshold']} msgs/{s['spam_window']}s → {s['spam_action'].upper()}",
            inline=False
        )
        embed.add_field(name="🔗 Links",
            value=f"{'✅' if s['links_enabled'] else '❌'} → {s['links_action'].upper()} | WL: {', '.join(wl) or 'None'}",
            inline=False
        )
        embed.add_field(name="🤬 Words",
            value=f"{'✅' if s['words_enabled'] else '❌'} {len(bw)} words → {s['words_action'].upper()}",
            inline=False
        )
        embed.add_field(name="🔠 Caps",
            value=f"{'✅' if s['caps_enabled'] else '❌'} {s['caps_threshold']}% / {s['caps_min_length']} chars → {s['caps_action'].upper()}",
            inline=False
        )
        embed.add_field(name="📣 Mentions",
            value=f"{'✅' if s['mention_enabled'] else '❌'} {s['mention_threshold']} mentions → {s['mention_action'].upper()}",
            inline=False
        )
        er_mentions = " ".join(f"<@&{r}>" for r in er) or "None"
        ec_mentions = " ".join(f"<#{c}>" for c in ec) or "None"
        embed.add_field(name="🛡 Exempt Roles",    value=er_mentions, inline=True)
        embed.add_field(name="🔇 Exempt Channels", value=ec_mentions, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    cog = AutoMod(bot)
    bot.tree.add_command(automod_group)
    await bot.add_cog(cog)
