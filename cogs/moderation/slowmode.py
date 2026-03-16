import discord
from discord import app_commands
from discord.ext import commands
from utils import db
from utils.helpers import success_embed, error_embed, send_log

class SlowmodeLock(commands.Cog):
    def __init__(self, bot): self.bot = bot

    # ── /slowmode ─────────────────────────────────────────
    @app_commands.command(name="slowmode", description="Set slowmode in a channel.")
    @app_commands.describe(
        seconds="Slowmode delay in seconds (0 = disable)",
        channel="Channel to apply to (default: current)"
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    async def slowmode(self, interaction: discord.Interaction,
                       seconds: app_commands.Range[int, 0, 21600] = 0,
                       channel: discord.TextChannel = None):
        target = channel or interaction.channel
        await target.edit(slowmode_delay=seconds)
        if seconds == 0:
            msg = f"Slowmode disabled in {target.mention}."
        else:
            msg = f"Slowmode set to `{seconds}s` in {target.mention}."
        await interaction.response.send_message(embed=success_embed("⏱️ Slowmode", msg), ephemeral=True)

    # ── /lockdown ─────────────────────────────────────────
    @app_commands.command(name="lockdown", description="Lock a channel so only staff can send messages.")
    @app_commands.describe(channel="Channel to lock (default: current)", reason="Reason")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lockdown(self, interaction: discord.Interaction,
                       channel: discord.TextChannel = None,
                       reason: str = "No reason provided"):
        target = channel or interaction.channel
        await target.set_permissions(
            interaction.guild.default_role,
            send_messages=False,
            reason=f"Lockdown by {interaction.user}: {reason}"
        )
        embed = discord.Embed(
            title="🔒 Channel Locked",
            description=f"{target.mention} has been locked.\n**Reason:** {reason}",
            color=0xED4245
        )
        await interaction.response.send_message(embed=embed)
        await target.send(embed=discord.Embed(
            title="🔒 This channel has been locked.",
            description=f"**Reason:** {reason}\nOnly staff can send messages.",
            color=0xED4245))
        await db.log_action(interaction.guild_id, "LOCKDOWN", interaction.user.id, target.id, reason)
        s = await db.get_guild_settings(interaction.guild_id)
        if s and s.get("log_channel"):
            await send_log(interaction.guild, s["log_channel"], embed)

    # ── /unlockdown ────────────────────────────────────────
    @app_commands.command(name="unlockdown", description="Unlock a locked channel.")
    @app_commands.describe(channel="Channel to unlock (default: current)", reason="Reason")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unlockdown(self, interaction: discord.Interaction,
                          channel: discord.TextChannel = None,
                          reason: str = "No reason provided"):
        target = channel or interaction.channel
        await target.set_permissions(
            interaction.guild.default_role,
            send_messages=None,
            reason=f"Unlock by {interaction.user}: {reason}"
        )
        embed = discord.Embed(
            title="🔓 Channel Unlocked",
            description=f"{target.mention} has been unlocked.\n**Reason:** {reason}",
            color=0x57F287
        )
        await interaction.response.send_message(embed=embed)
        await target.send(embed=discord.Embed(
            title="🔓 This channel is now unlocked.", color=0x57F287))
        await db.log_action(interaction.guild_id, "UNLOCKDOWN", interaction.user.id, target.id, reason)

    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=error_embed("Missing Permissions"), ephemeral=True)

async def setup(bot): await bot.add_cog(SlowmodeLock(bot))
