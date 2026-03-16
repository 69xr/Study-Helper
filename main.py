"""
main.py  —  Bot entry point
"""
import discord
from discord.ext import commands
import asyncio
import os
import config
from utils import db


# ═══════════════════════════════════════════════════════════════
#  INTENTS
# ═══════════════════════════════════════════════════════════════

intents = discord.Intents.default()
intents.members         = True
intents.message_content = True
intents.guilds          = True


# ═══════════════════════════════════════════════════════════════
#  BOT CLASS
# ═══════════════════════════════════════════════════════════════

class Bot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=config.PREFIX,
            intents=intents,
            owner_id=config.OWNER_ID,
            help_command=None,   # we use slash commands
        )

    # ── Startup ──────────────────────────────────────────────
    async def setup_hook(self):
        # 1. Ensure data folder + init DB
        os.makedirs(config.DATA_DIR, exist_ok=True)
        await db.init_db()
        await db.init_new_tables()
        print("  💾  Database ready.")

        # 2. Load cogs
        cogs = [
            # ── General ─────────────────────────
            "cogs.general.ping",
            "cogs.general.avatar",
            "cogs.general.uptime",
            "cogs.general.serverinfo",
            "cogs.general.userinfo",
            "cogs.general.snipe",
            "cogs.general.help",
            # ── Moderation ───────────────────────
            "cogs.moderation.kick",
            "cogs.moderation.ban",
            "cogs.moderation.warn",
            "cogs.moderation.clear",
            "cogs.moderation.mute",
            "cogs.moderation.slowmode",
            # ── Economy ──────────────────────────
            "cogs.economy.balance",
            "cogs.economy.daily",
            "cogs.economy.pay",
            "cogs.economy.shop",
            "cogs.economy.admin",
            "cogs.economy.bank",
            "cogs.economy.robslots",
            # ── Leveling ─────────────────────────
            "cogs.leveling.rank",
            "cogs.leveling.setup",
            "cogs.leveling.admin",
            # ── Roles ────────────────────────────
            "cogs.roles.panels",
            # ── Settings ─────────────────────────
            "cogs.settings.config",
            "cogs.settings.aliases",
            # ── Tickets ──────────────────────────
            "cogs.tickets.tickets",
            # ── AutoMod ──────────────────────────
            "cogs.automod",
            # ── Temp Rooms ───────────────────────
            "cogs.temprooms.rooms",
            "cogs.temprooms.invite",
            # ── Suggestions ──────────────────────
            "cogs.suggestions.suggestions",
            # ── Owner ────────────────────────────
            "cogs.owner",
        ]
        for cog in cogs:
            try:
                await self.load_extension(cog)
                print(f"  ✅  {cog}")
            except Exception as e:
                print(f"  ❌  {cog}: {e}")

        # 3. Re-register all persistent role-panel views from DB
        await self._restore_role_panels()

        # 4. Attach global interaction check (blacklist) to the app command tree
        self.tree.interaction_check = self.interaction_check_global

        # 5. Sync slash commands to Discord
        # Guild sync is INSTANT. Global sync can take up to 1 hour.
        # We do both: guild sync so commands appear immediately,
        # global sync so the bot works in all servers.
        synced_global = await self.tree.sync()
        print(f"\n🌐  Global sync: {len(synced_global)} command(s).")

        # Instant guild sync for every connected guild
        total_guild = 0
        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                synced_guild = await self.tree.sync(guild=guild)
                total_guild += len(synced_guild)
            except Exception as e:
                print(f"  ⚠️  Guild sync failed for {guild.name}: {e}")
        print(f"⚡  Guild sync: {total_guild} command(s) across {len(self.guilds)} guild(s) — INSTANT.\n")

    async def _restore_role_panels(self):
        """Re-attach persistent button views so old panels still work after restart."""
        from cogs.roles.panels import RolePickerView
        panels = await db.get_all_panels_for_restore()
        for panel in panels:
            view = RolePickerView(panel["entries"])
            self.add_view(view)
        print(f"  🔄  Restored {len(panels)} role panel view(s).")

    # ── Blacklist check — uses tree.interaction_check (discord.py v2 correct pattern)
    async def interaction_check_global(self, interaction: discord.Interaction) -> bool:
        if interaction.user:
            bl = await db.is_blacklisted(interaction.user.id)
            if bl:
                try:
                    await interaction.response.send_message(
                        f"🚫 You are blacklisted from using this bot.\n**Reason:** {bl['reason']}",
                        ephemeral=True
                    )
                except Exception:
                    pass
                return False
        return True

    # ── Suppress CommandNotFound for prefix aliases ─────────
    # When a user types !alias (e.g. !bal), discord.py fires CommandNotFound
    # because !bal is not a registered prefix command — it's handled by
    # the on_message alias system in settings.py instead.
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return  # silently ignore — aliases handle this in on_message
        # Re-raise everything else so real errors are still logged
        raise error

    # ── Log command usage ─────────────────────────────────────
    async def on_app_command_completion(self, interaction: discord.Interaction, command):
        if interaction.guild_id:
            await db.log_command(command.name, interaction.guild_id, interaction.user.id)

    # ── Ready ─────────────────────────────────────────────────
    async def on_ready(self):
        print("=" * 50)
        print(f"  🤖  {self.user}  ({self.user.id})")
        print(f"  📡  {len(self.guilds)} guild(s) connected")
        print("=" * 50)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=config.STATUS
            )
        )

    # ── Auto-init guild settings when joining ────────────────
    async def on_guild_join(self, guild: discord.Guild):
        await db.ensure_guild(guild.id)
        print(f"  ➕  Joined guild: {guild.name} ({guild.id})")


bot = Bot()

if __name__ == "__main__":
    bot.run(config.TOKEN)
