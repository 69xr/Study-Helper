"""
cogs/ipc_bridge.py — Bot ↔ Dashboard IPC Cog
Polls for dashboard commands every 2 seconds.
Writes ACK for every command so the dashboard can confirm execution.
"""
import asyncio, traceback, logging
import discord
from discord.ext import commands, tasks
from utils.ipc import bot_emit, bot_ack, bot_read_commands, write_module_state, read_module_state
from utils.product_catalog import module_catalog

log = logging.getLogger("severus.ipc")

# Map cog display names → extension paths
class IPCBridge(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._maintenance_guilds: set[int] = set()

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.poll_commands.is_running():
            self.poll_commands.start()

    def cog_unload(self):
        if self.poll_commands.is_running():
            self.poll_commands.cancel()

    def _module_catalog(self):
        canonical = getattr(self.bot, "canonical_cogs", tuple(self.bot.extensions.keys()))
        return module_catalog(canonical)

    def _snapshot_modules(self):
        prior = read_module_state()
        snapshot = {}
        for key, meta in self._module_catalog().items():
            cached = prior.get(key, {})
            loaded = meta["ext"] in self.bot.extensions
            snapshot[key] = {
                "enabled": loaded,
                "loaded": loaded,
                "maintenance": cached.get("maintenance", False),
                "maintenance_reason": cached.get("maintenance_reason", ""),
                "reason": cached.get("maintenance_reason", ""),
                "ext": meta["ext"],
                "name": meta["name"],
                "description": meta["description"],
                "manageable": meta["manageable"],
            }
        write_module_state(snapshot)
        return snapshot

    # ── Command poller ────────────────────────────────────────

    @tasks.loop(seconds=2)
    async def poll_commands(self):
        cmds = bot_read_commands()
        for cmd in cmds:
            action = cmd.get("action", "")
            params = cmd.get("params", {})
            cid    = cmd.get("cmd_id", "?")
            try:
                await self._dispatch(action, params, cid)
            except Exception as e:
                tb = traceback.format_exc()
                bot_emit("ERROR", f"IPC '{action}' raised: {e}")
                bot_ack(cid, False, f"Exception: {e}\n{tb[:300]}")

    @poll_commands.before_loop
    async def _before_poll(self):
        try:
            await self.bot.wait_until_ready()
        except RuntimeError:
            self.poll_commands.stop()
            return
        self._snapshot_modules()
        bot_emit("SUCCESS", f"IPC bridge online — {self.bot.user}")

    # ── Dispatcher ────────────────────────────────────────────

    async def _dispatch(self, action: str, params: dict, cid: str):
        log.info(f"IPC action: {action} (id={cid})")

        # ── reload_cogs ──────────────────────────────────────
        if action == "reload_cogs":
            ok_list, fail_list = [], []
            for ext in list(self.bot.extensions.keys()):
                try:
                    await self.bot.reload_extension(ext)
                    ok_list.append(ext)
                except Exception as e:
                    fail_list.append(f"{ext}: {e}")
            msg = f"Reloaded {len(ok_list)} cog(s)."
            if fail_list:
                msg += f" Failed: {', '.join(fail_list)}"
            self._snapshot_modules()
            bot_emit("SUCCESS" if not fail_list else "WARN", msg)
            bot_ack(cid, not fail_list, msg, {"reloaded": ok_list, "failed": fail_list})

        # ── sync_commands ────────────────────────────────────
        elif action == "sync_commands":
            try:
                if hasattr(self.bot, "_sync_application_commands"):
                    await self.bot._sync_application_commands()
                    synced = self.bot.tree.get_commands()
                    msg = f"Synced {len(synced)} slash command(s) and cleaned dev overrides."
                else:
                    synced = await self.bot.tree.sync()
                    msg = f"Synced {len(synced)} slash command(s) globally."
                bot_emit("SUCCESS", msg)
                bot_ack(cid, True, msg, {"count": len(synced)})
            except Exception as e:
                bot_emit("ERROR", f"Sync failed: {e}")
                bot_ack(cid, False, f"Sync failed: {e}")

        # ── set_status ───────────────────────────────────────
        elif action == "set_status":
            text  = params.get("text", "your server 👀")
            stype = params.get("type", "watching")
            atype = {
                "watching":  discord.ActivityType.watching,
                "playing":   discord.ActivityType.playing,
                "listening": discord.ActivityType.listening,
                "competing": discord.ActivityType.competing,
            }.get(stype, discord.ActivityType.watching)
            await self.bot.change_presence(
                activity=discord.Activity(type=atype, name=text))
            msg = f"Status → {stype} '{text}'"
            bot_emit("SUCCESS", msg)
            bot_ack(cid, True, msg)

        # ── shutdown ─────────────────────────────────────────
        elif action == "shutdown":
            bot_emit("WARN", "Graceful shutdown requested from dashboard.")
            bot_ack(cid, True, "Shutting down in 1 second…")
            await asyncio.sleep(1)
            await self.bot.close()

        # ── enable_module ────────────────────────────────────
        elif action == "enable_module":
            module = params.get("module")
            meta   = self._module_catalog().get(module)
            if not meta:
                bot_ack(cid, False, f"Unknown module: {module}")
                return
            if not meta["manageable"]:
                bot_ack(cid, False, f"Module '{module}' is locked for dashboard safety.")
                return
            ext = meta["ext"]
            if ext in self.bot.extensions:
                bot_ack(cid, True, f"{module} is already loaded.")
                return
            try:
                await self.bot.load_extension(ext)
                self._snapshot_modules()
                msg = f"Module '{module}' enabled."
                bot_emit("SUCCESS", msg)
                bot_ack(cid, True, msg)
            except Exception as e:
                bot_emit("ERROR", f"Failed to enable {module}: {e}")
                bot_ack(cid, False, f"Failed: {e}")

        # ── disable_module ───────────────────────────────────
        elif action == "disable_module":
            module = params.get("module")
            meta   = self._module_catalog().get(module)
            if not meta:
                bot_ack(cid, False, f"Unknown module: {module}")
                return
            if not meta["manageable"]:
                bot_ack(cid, False, f"Module '{module}' is locked for dashboard safety.")
                return
            ext = meta["ext"]
            if ext not in self.bot.extensions:
                bot_ack(cid, True, f"{module} is already unloaded.")
                return
            try:
                await self.bot.unload_extension(ext)
                self._snapshot_modules()
                msg = f"Module '{module}' disabled."
                bot_emit("WARN", msg)
                bot_ack(cid, True, msg)
            except Exception as e:
                bot_emit("ERROR", f"Failed to disable {module}: {e}")
                bot_ack(cid, False, f"Failed: {e}")

        # ── maintenance_mode ─────────────────────────────────
        elif action == "maintenance_mode":
            module     = params.get("module")
            enable     = params.get("enable", True)
            reason     = params.get("reason", "Under maintenance")
            guild_id   = params.get("guild_id")  # None = all guilds
            if module not in self._module_catalog():
                bot_ack(cid, False, f"Unknown module: {module}")
                return
            state      = read_module_state()
            if module not in state:
                state[module] = {"enabled": True, "maintenance": False}
            state[module]["maintenance"]        = enable
            state[module]["maintenance_reason"] = reason if enable else ""
            write_module_state(state)
            self._snapshot_modules()
            mode = "enabled" if enable else "disabled"
            msg  = f"Maintenance mode {mode} for '{module}'. Reason: {reason}"
            bot_emit("WARN" if enable else "SUCCESS", msg)
            bot_ack(cid, True, msg)

        # ── post_verify ──────────────────────────────────────
        elif action == "post_verify":
            from cogs.security.security import VerifyView
            from utils import db
            guild_id   = params.get("guild_id")
            channel_id = params.get("channel_id")
            guild      = self.bot.get_guild(int(guild_id)) if guild_id else None
            channel    = self.bot.get_channel(int(channel_id)) if channel_id else None
            if not guild or not channel:
                bot_ack(cid, False, "Guild or channel not found.")
                return
            s = await db.get_guild_settings(guild.id)
            verify_role_id = s.get("verify_role") if s else None
            role_name = "Verified"
            if verify_role_id:
                r = guild.get_role(int(verify_role_id))
                if r:
                    role_name = r.name
            embed = discord.Embed(
                title=f"✅  Welcome to {guild.name}",
                description=(
                    f"Click the button below to verify you're human and gain access.\n\n"
                    f"You'll receive the **{role_name}** role."
                ),
                color=0x57F287,
            )
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)
            embed.set_footer(text="Severus Verification System")
            try:
                await channel.send(embed=embed, view=VerifyView())
                msg = f"Verification embed posted in #{channel.name}."
                bot_emit("SUCCESS", msg)
                bot_ack(cid, True, msg)
            except discord.Forbidden:
                bot_ack(cid, False, "Missing permissions to post in that channel.")

        # ── send_embed ───────────────────────────────────────
        elif action == "send_embed":
            channel_id = params.get("channel_id")
            embed_data  = params.get("embed", {})
            content     = params.get("content") or None
            channel     = self.bot.get_channel(int(channel_id)) if channel_id else None
            if not channel:
                bot_ack(cid, False, "Channel not found — is the bot in that server?")
                return
            try:
                color = embed_data.get("color", 0x5865F2)
                embed = discord.Embed(
                    title       = embed_data.get("title") or None,
                    description = embed_data.get("description") or None,
                    url         = embed_data.get("url") or None,
                    color       = color,
                )
                if embed_data.get("author"):
                    a = embed_data["author"]
                    embed.set_author(
                        name     = a.get("name", ""),
                        url      = a.get("url") or None,
                        icon_url = a.get("icon_url") or None,
                    )
                for field in embed_data.get("fields", []):
                    embed.add_field(
                        name   = field.get("name", "\u200b"),
                        value  = field.get("value", "\u200b"),
                        inline = field.get("inline", False),
                    )
                if embed_data.get("image"):
                    embed.set_image(url=embed_data["image"].get("url", ""))
                if embed_data.get("thumbnail"):
                    embed.set_thumbnail(url=embed_data["thumbnail"].get("url", ""))
                if embed_data.get("footer"):
                    ft = embed_data["footer"]
                    embed.set_footer(
                        text     = ft.get("text", ""),
                        icon_url = ft.get("icon_url") or None,
                    )
                if embed_data.get("timestamp"):
                    from datetime import datetime, timezone
                    embed.timestamp = datetime.now(timezone.utc)
                await channel.send(content=content, embed=embed)
                msg = f"Embed sent to #{channel.name}."
                bot_emit("SUCCESS", msg)
                bot_ack(cid, True, msg)
            except discord.Forbidden:
                bot_ack(cid, False, "Missing permission to send in that channel.")
            except Exception as e:
                bot_ack(cid, False, f"Failed to build/send embed: {e}")

        # ── clear_stats ──────────────────────────────────────
        elif action == "clear_stats":
            from utils import db as _db
            guild_id = params.get("guild_id")
            async with __import__("aiosqlite").connect(_db.DB_PATH) as conn:
                if guild_id:
                    await conn.execute(
                        "DELETE FROM command_stats WHERE guild_id=?", (int(guild_id),))
                    msg = f"Stats cleared for guild {guild_id}."
                else:
                    await conn.execute("DELETE FROM command_stats")
                    msg = "All command stats cleared."
                await conn.commit()
            bot_emit("WARN", msg)
            bot_ack(cid, True, msg)

        # ── vacuum_db ────────────────────────────────────────
        elif action == "vacuum_db":
            from utils import db as _db
            async with __import__("aiosqlite").connect(_db.DB_PATH) as conn:
                await conn.execute("VACUUM")
            msg = "SQLite VACUUM complete — disk space reclaimed."
            bot_emit("SUCCESS", msg)
            bot_ack(cid, True, msg)

        # ── get_module_state ─────────────────────────────────
        elif action == "get_module_state":
            state = self._snapshot_modules()
            bot_ack(cid, True, "Module state fetched.", {"modules": state})

        else:
            bot_ack(cid, False, f"Unknown action: '{action}'")

    # ── Event emitters ────────────────────────────────────────

    @commands.Cog.listener()
    async def on_app_command_completion(self, interaction: discord.Interaction, command):
        bot_emit("CMD",
                 f"/{command.name} → {interaction.user} in {getattr(interaction.guild,'name','DM')}",
                 guild_id=interaction.guild_id)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        bot_emit("INFO", f"Join: {member} → {member.guild.name}", guild_id=member.guild.id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        bot_emit("INFO", f"Left: {member} ← {member.guild.name}", guild_id=member.guild.id)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        bot_emit("SUCCESS", f"Bot joined: {guild.name} ({guild.id})")

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        bot_emit("WARN", f"Bot removed from: {guild.name} ({guild.id})")

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        preview = str(message.content)[:80]
        bot_emit("INFO",
                 f"Deleted in #{message.channel.name}: {preview!r}",
                 guild_id=message.guild.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(IPCBridge(bot))
