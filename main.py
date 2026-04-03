"""
main.py  —  Severus Bot — Production Entry Point
"""
import discord
from discord.ext import commands
import asyncio, logging, os, sys, traceback
import config
from utils import db
from utils.focus_image_engine import ImageEngine

# ═══════════════════════════════════════════════════════════════
#  LOGGING
# ═══════════════════════════════════════════════════════════════

os.makedirs("data", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/severus.log", encoding="utf-8", mode="a"),
    ],
)
log = logging.getLogger("severus")

logging.getLogger("discord.http").setLevel(logging.WARNING)
logging.getLogger("discord.gateway").setLevel(logging.WARNING)
logging.getLogger("discord.client").setLevel(logging.WARNING)

# ═══════════════════════════════════════════════════════════════
#  INTENTS
# ═══════════════════════════════════════════════════════════════

intents = discord.Intents.default()
intents.members         = True
intents.message_content = True
intents.guilds          = True

# ═══════════════════════════════════════════════════════════════
#  COG LIST
# ═══════════════════════════════════════════════════════════════

COGS = [
    "cogs.general.ping",
    "cogs.general.avatar",
    "cogs.general.uptime",
    "cogs.general.serverinfo",
    "cogs.general.userinfo",
    "cogs.general.snipe",
    "cogs.general.help",
    "cogs.general.reminders",
    "cogs.general.afk",
    "cogs.moderation.kick",
    "cogs.moderation.ban",
    "cogs.moderation.warn",
    "cogs.moderation.clear",
    "cogs.moderation.mute",
    "cogs.moderation.slowmode",
    "cogs.moderation.timeout",
    "cogs.moderation.notes",
    "cogs.moderation.thresholds",
    "cogs.roles.panels",
    "cogs.settings.config",
    "cogs.settings.aliases",
    "cogs.automod",
    "cogs.logging.logger",
    "cogs.temprooms.rooms",
    "cogs.community.custom_commands",
    "cogs.community.autoroles",
    "cogs.community.polls",
    "cogs.community.starboard",
    "cogs.focus.timer",
    "cogs.focus.profile",
    "cogs.focus.pets",
    "cogs.music.player",
    "cogs.music.lyrics",
    "cogs.security.security",
    "cogs.owner",
    "cogs.ipc_bridge",
]

# ═══════════════════════════════════════════════════════════════
#  BOT
# ═══════════════════════════════════════════════════════════════

class Bot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=config.PREFIX,
            intents=intents,
            owner_id=config.OWNER_ID,
            help_command=None,
        )
        self.canonical_cogs = tuple(COGS)
        self.focus_image_engine = ImageEngine()

    async def setup_hook(self):
        os.makedirs(config.DATA_DIR, exist_ok=True)

        # 1. Database
        await db.init_db()
        await db.init_new_tables()
        await db.cleanup_removed_features()
        await db.clear_focus_timers()
        log.info("Database ready.")

        # 2. Load every cog — each cog's setup() calls bot.add_cog()
        #    which registers its app_commands into self.tree automatically.
        failed = []
        for cog in COGS:
            try:
                await self.load_extension(cog)
                log.info(f"  OK  {cog}")
            except Exception as e:
                log.error(f"  ❌  {cog}: {e}\n{traceback.format_exc()}")
                failed.append(cog)

        if failed:
            log.warning(f"{len(failed)} cog(s) failed to load: {failed}")

        # 3. Restore persistent views
        await self._restore_role_panels()
        await self._restore_verify_views()

        # 4. Global blacklist check on every interaction
        self.tree.interaction_check = self.interaction_check_global

        if self.application_id:
            await self._sync_application_commands()
        else:
            log.info("Skipping slash-command sync because application_id is not ready yet.")

    async def _sync_application_commands(self) -> None:
        """Sync global commands and remove stale dev-guild overrides."""
        log.info("Syncing slash commands with Discord...")
        try:
            synced = await self.tree.sync()
            log.info(f"OK  Global sync complete: {len(synced)} command(s) registered.")
        except discord.HTTPException as e:
            log.error(f"Global sync failed: {e}")
            return

        dev_guild_id = getattr(config, "DEV_GUILD_ID", None)
        if not dev_guild_id:
            return

        try:
            dev_guild = discord.Object(id=int(dev_guild_id))
            # Clear old guild-scoped copies so the dev server only shows the global commands.
            self.tree.clear_commands(guild=dev_guild)
            await self.tree.sync(guild=dev_guild)
            log.info("OK  Cleared dev guild-specific slash command overrides.")
        except Exception as e:
            log.warning(f"Dev guild cleanup failed: {e}")

    # ── Persistent view restore ───────────────────────────────

    async def _restore_role_panels(self):
        try:
            from cogs.roles.panels import RolePickerView
            panels = await db.get_all_panels_for_restore()
            for panel in panels:
                self.add_view(RolePickerView(panel["entries"]))
            log.info(f"Restored {len(panels)} role panel view(s).")
        except Exception as e:
            log.warning(f"Role panel restore failed: {e}")

    async def _restore_verify_views(self):
        try:
            from cogs.security.security import VerifyView
            self.add_view(VerifyView())
            log.info("VerifyView restored.")
        except Exception as e:
            log.warning(f"VerifyView restore failed: {e}")

    # ── Blacklist gate ────────────────────────────────────────

    async def interaction_check_global(self, interaction: discord.Interaction) -> bool:
        if interaction.user:
            bl = await db.is_blacklisted(interaction.user.id)
            if bl:
                try:
                    await interaction.response.send_message(
                        f"🚫 You are blacklisted from using this bot.\n**Reason:** {bl['reason']}",
                        ephemeral=True,
                    )
                except Exception:
                    pass
                return False
        return True

    # ── Error handlers ────────────────────────────────────────

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return  # aliases handle unknown prefix commands
        log.error(f"Prefix command error: {error}", exc_info=error)

    async def on_app_command_error(self, interaction: discord.Interaction, error):
        """Global fallback — individual cogs should handle their own errors first."""
        log.error(f"Slash command error [{getattr(interaction.command,'name','?')}]: {error}", exc_info=error)
        msg = "An unexpected error occurred."
        if isinstance(error, discord.app_commands.MissingPermissions):
            msg = "You don't have permission to use this command."
        elif isinstance(error, discord.app_commands.BotMissingPermissions):
            perms = ", ".join(error.missing_permissions)
            msg = f"I'm missing permissions: `{perms}`"
        elif isinstance(error, discord.app_commands.CommandOnCooldown):
            msg = f"Slow down! Retry in `{error.retry_after:.1f}s`."
        elif isinstance(error, discord.app_commands.CheckFailure):
            msg = "You don't meet the requirements for this command."
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ {msg}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ {msg}", ephemeral=True)
        except Exception:
            pass

    # ── Logging ───────────────────────────────────────────────

    async def on_app_command_completion(self, interaction: discord.Interaction, command):
        if interaction.guild_id:
            await db.log_command(command.name, interaction.guild_id, interaction.user.id)

    async def on_ready(self):
        log.info("=" * 52)
        log.info(f"  🤖  Logged in as {self.user}  ({self.user.id})")
        log.info(f"  📡  Connected to {len(self.guilds)} guild(s)")
        log.info("=" * 52)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=config.STATUS,
            )
        )

    async def on_guild_join(self, guild: discord.Guild):
        await db.ensure_guild(guild.id)
        log.info(f"Joined: {guild.name} ({guild.id})")

    async def on_resumed(self):
        log.info("Gateway session resumed.")

    async def on_disconnect(self):
        log.warning("Disconnected from Discord gateway.")


# ═══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════

bot = Bot()

if __name__ == "__main__":
    try:
        bot.run(config.TOKEN, log_handler=None)
    except discord.LoginFailure:
        log.critical("Invalid bot token — set config.TOKEN correctly.")
        sys.exit(1)
    except Exception as e:
        log.critical(f"Fatal error at startup: {e}", exc_info=True)
        sys.exit(1)
