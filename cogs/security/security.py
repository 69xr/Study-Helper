"""
cogs/security/security.py
Security: anti-raid, verification gate, emergency lockdown.
Configuration (verify roles, antiraid settings) → Dashboard only.
Emergency commands (/lockserver, /unlockserver) stay in Discord.
"""
import discord, asyncio, logging
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
from collections import defaultdict
from utils import db
from utils.helpers import success_embed, error_embed, send_log
import config

log = logging.getLogger("severus.security")

# ── State ──────────────────────────────────────────────────────
_join_log:  dict[int, list[datetime]] = defaultdict(list)
_raid_mode: set[int]                  = set()


# ── Verification View (persistent) ────────────────────────────

class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="✅  Verify — I'm not a bot",
        style=discord.ButtonStyle.success,
        custom_id="verify_btn",
    )
    async def verify(self, interaction: discord.Interaction, btn: discord.ui.Button):
        s = await db.get_guild_settings(interaction.guild_id)
        if not s or not s.get("verify_role"):
            await interaction.response.send_message(
                embed=error_embed("Not Configured", "No verification role set. Configure in the Dashboard."),
                ephemeral=True)
            return
        role = interaction.guild.get_role(int(s["verify_role"]))
        if not role:
            await interaction.response.send_message(
                embed=error_embed("Role Missing", "The verification role no longer exists."),
                ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.response.send_message(
                embed=success_embed("Already Verified", "You already have full access!"),
                ephemeral=True)
            return
        # Remove unverified role if set
        unverified_id = s.get("unverified_role")
        if unverified_id:
            unv = interaction.guild.get_role(int(unverified_id))
            if unv and unv in interaction.user.roles:
                try:
                    await interaction.user.remove_roles(unv, reason="Verification passed")
                except Exception:
                    pass
        try:
            await interaction.user.add_roles(role, reason="Member self-verified")
            await interaction.response.send_message(
                embed=success_embed("✅  Verified!", "You now have full server access."),
                ephemeral=True)
            log.info(f"User {interaction.user} verified in {interaction.guild}")
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=error_embed("Failed", "I can't assign roles — check my permissions."),
                ephemeral=True)


# ── Cog ───────────────────────────────────────────────────────

class Security(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(VerifyView())

    # ── Anti-raid join monitor ─────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild_id = member.guild.id
        now      = datetime.now(timezone.utc)

        # Rolling 60-second window
        _join_log[guild_id].append(now)
        _join_log[guild_id] = [
            t for t in _join_log[guild_id]
            if (now - t).total_seconds() < 60
        ]

        s = await db.get_guild_settings(guild_id)
        if not s:
            return

        # Kick accounts that are too new
        min_age = s.get("min_account_age", 0) or 0
        if min_age > 0:
            age_days = (now - member.created_at).days
            if age_days < min_age:
                try:
                    await member.send(
                        embed=discord.Embed(
                            description=(
                                f"You can't join **{member.guild.name}** yet.\n"
                                f"Minimum account age: **{min_age} days** — yours: **{age_days} days**."
                            ),
                            color=config.Colors.ERROR,
                        )
                    )
                except Exception:
                    pass
                try:
                    await member.kick(reason=f"Account too new ({age_days}d < {min_age}d)")
                except Exception:
                    pass
                return

        # Raid detection
        threshold = int(s.get("raid_threshold", 10) or 10)
        if (
            len(_join_log[guild_id]) >= threshold
            and guild_id not in _raid_mode
            and s.get("anti_raid", 0)
        ):
            _raid_mode.add(guild_id)
            asyncio.create_task(self._activate_raid_mode(member.guild, s))

        # Assign unverified role
        unv_id = s.get("unverified_role")
        if unv_id:
            role = member.guild.get_role(int(unv_id))
            if role:
                try:
                    await member.add_roles(role, reason="Unverified new member")
                except Exception:
                    pass

    async def _activate_raid_mode(self, guild: discord.Guild, settings: dict):
        embed = discord.Embed(
            title="🚨  RAID DETECTED — Server Locked",
            description=(
                "**Unusual join spike detected.**\n\n"
                "All channels locked automatically.\n"
                "Use `/unlockserver` when safe."
            ),
            color=config.Colors.ERROR,
        )
        embed.set_footer(text=config.FOOTER_TEXT)

        for ch in guild.text_channels:
            try:
                await ch.set_permissions(
                    guild.default_role,
                    send_messages=False,
                    reason="Anti-raid auto-lockdown",
                )
            except Exception:
                pass

        if settings.get("log_channel"):
            lch = guild.get_channel(int(settings["log_channel"]))
            if lch:
                try:
                    await lch.send(embed=embed)
                except Exception:
                    pass

        log.warning(f"Raid mode activated in {guild.name} ({guild.id})")
        await asyncio.sleep(600)
        _raid_mode.discard(guild.id)
        log.info(f"Raid mode expired in {guild.name} ({guild.id})")

    # ── Emergency Slash Commands (Discord-only, no Dashboard equivalent) ──

    @app_commands.command(name="lockserver", description="Emergency: lock all text channels immediately.")
    @app_commands.describe(reason="Reason for lockdown")
    @app_commands.checks.has_permissions(administrator=True)
    async def lockserver(self, interaction: discord.Interaction, reason: str = "Emergency lockdown"):
        await interaction.response.defer()
        locked = failed = 0
        everyone = interaction.guild.default_role
        for ch in interaction.guild.text_channels:
            try:
                await ch.set_permissions(everyone, send_messages=False,
                    reason=f"Lockdown by {interaction.user}: {reason}")
                locked += 1
            except Exception:
                failed += 1
        embed = discord.Embed(
            title="🔒  Server Locked",
            description=f"**{locked}** channels locked, **{failed}** skipped.\n**Reason:** {reason}\n\nUse `/unlockserver` to restore.",
            color=config.Colors.ERROR,
        )
        embed.set_footer(text=config.FOOTER_TEXT)
        await interaction.followup.send(embed=embed)
        s = await db.get_guild_settings(interaction.guild_id)
        if s and s.get("log_channel"):
            await send_log(interaction.guild, s["log_channel"], embed)

    @app_commands.command(name="unlockserver", description="Emergency: restore text channel sending after a lockdown.")
    @app_commands.checks.has_permissions(administrator=True)
    async def unlockserver(self, interaction: discord.Interaction):
        await interaction.response.defer()
        unlocked = 0
        everyone = interaction.guild.default_role
        for ch in interaction.guild.text_channels:
            try:
                await ch.set_permissions(everyone, send_messages=None,
                    reason=f"Unlock by {interaction.user}")
                unlocked += 1
            except Exception:
                pass
        await interaction.followup.send(
            embed=success_embed("🔓  Server Unlocked", f"**{unlocked}** channels restored."))

    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=error_embed("Missing Permissions", "**Administrator** required."),
                    ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Security(bot))
