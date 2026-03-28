"""
cogs/owner.py
Commands: /blacklist  /unblacklist  /blacklistview
          /reload  /shutdown  /announce  /botstats  /dm
All owner-only — restricted to OWNER_ID in config.py
"""
import discord
from discord import app_commands
from discord.ext import commands
import config
from utils import db
from utils.helpers import success_embed, error_embed, warning_embed


# ── Owner check ───────────────────────────────────────────────

def is_owner():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id != config.OWNER_ID:
            await interaction.response.send_message(
                embed=error_embed("Owner Only", "This command can only be used by the bot owner."),
                ephemeral=True
            )
            return False
        return True
    return app_commands.check(predicate)


class Owner(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _resolve_reload_targets(self, cog: str) -> list[str]:
        query = cog.strip().lower()
        if query == "all":
            canonical = list(getattr(self.bot, "canonical_cogs", ()))
            return canonical or list(self.bot.extensions.keys())

        loaded = list(self.bot.extensions.keys())
        aliases = {
            ext.lower(): ext for ext in loaded
        }
        for ext in loaded:
            short = ext.removeprefix("cogs.").lower()
            aliases.setdefault(short, ext)
            aliases.setdefault(short.split(".")[-1], ext)

        target = aliases.get(query)
        if target:
            return [target]

        return [f"cogs.{query}"]

    # ── /blacklist ────────────────────────────────────────────
    @app_commands.command(name="blacklist", description="Owner: block a user from using the bot.")
    @app_commands.describe(user_id="The user's Discord ID", reason="Why they are blacklisted")
    @is_owner()
    async def blacklist(self, interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
        try:
            uid = int(user_id)
        except ValueError:
            await interaction.response.send_message(embed=error_embed("Invalid ID", "Not a valid user ID."), ephemeral=True)
            return

        existing = await db.is_blacklisted(uid)
        if existing:
            await interaction.response.send_message(
                embed=warning_embed("Already Blacklisted", f"User `{uid}` is already blacklisted."),
                ephemeral=True
            )
            return

        await db.add_to_blacklist(uid, reason, interaction.user.id)

        try:
            user = await self.bot.fetch_user(uid)
            user_str = str(user)
        except Exception:
            user_str = f"ID: {uid}"

        embed = discord.Embed(title="🚫  User Blacklisted", color=0xED4245)
        embed.add_field(name="User",   value=user_str, inline=True)
        embed.add_field(name="Reason", value=reason,   inline=False)
        await interaction.response.send_message(embed=embed)

    # ── /unblacklist ──────────────────────────────────────────
    @app_commands.command(name="unblacklist", description="Owner: remove a user from the blacklist.")
    @app_commands.describe(user_id="The user's Discord ID")
    @is_owner()
    async def unblacklist(self, interaction: discord.Interaction, user_id: str):
        try:
            uid = int(user_id)
        except ValueError:
            await interaction.response.send_message(embed=error_embed("Invalid ID", "Not a valid user ID."), ephemeral=True)
            return

        removed = await db.remove_from_blacklist(uid)
        if not removed:
            await interaction.response.send_message(
                embed=error_embed("Not Found", f"User `{uid}` is not blacklisted."),
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            embed=success_embed("Unblacklisted", f"User `{uid}` has been removed from the blacklist.")
        )

    # ── /blacklistview ────────────────────────────────────────
    @app_commands.command(name="blacklistview", description="Owner: review all blacklisted users.")
    @is_owner()
    async def blacklistview(self, interaction: discord.Interaction):
        bl = await db.get_blacklist()
        if not bl:
            await interaction.response.send_message(
                embed=success_embed("Blacklist Empty", "No users are currently blacklisted."),
                ephemeral=True
            )
            return

        embed = discord.Embed(title="🚫  Blacklisted Users", color=0xED4245)
        for entry in bl[:20]:
            try:
                user = await self.bot.fetch_user(entry["user_id"])
                user_str = str(user)
            except Exception:
                user_str = f"ID: {entry['user_id']}"
            embed.add_field(
                name=user_str,
                value=f"**Reason:** {entry['reason']}\n**Date:** {entry['added_at'][:10]}",
                inline=False
            )
        embed.set_footer(text=f"Total: {len(bl)}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /reload ───────────────────────────────────────────────
    @app_commands.command(name="reload", description="Owner: reload one module or the full bot command stack.")
    @app_commands.describe(cog="Cog name, e.g. moderation | all to reload everything")
    @is_owner()
    async def reload(self, interaction: discord.Interaction, cog: str):
        await interaction.response.defer(ephemeral=True)
        cogs_to_reload = self._resolve_reload_targets(cog)

        results = []
        for c in cogs_to_reload:
            try:
                if c in self.bot.extensions:
                    await self.bot.reload_extension(c)
                else:
                    await self.bot.load_extension(c)
                results.append(f"✅ `{c}`")
            except Exception as e:
                results.append(f"❌ `{c}` - {e}")

        await interaction.followup.send(
            embed=discord.Embed(
                title="🔄  Reload Results",
                description="\n".join(results),
                color=0x5865F2
            ),
            ephemeral=True
        )

    # ── /shutdown ─────────────────────────────────────────────
    @app_commands.command(name="shutdown", description="Owner: gracefully shut down the bot.")
    @is_owner()
    async def shutdown(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=warning_embed("Shutting Down", "Bot is going offline..."),
            ephemeral=True
        )
        await self.bot.close()

    # ── /announce ─────────────────────────────────────────────
    @app_commands.command(name="announce", description="Owner: send a branded announcement to a channel.")
    @app_commands.describe(channel="Target channel", title="Embed title", message="Embed body", ping_everyone="Ping @everyone?")
    @is_owner()
    async def announce(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        title: str,
        message: str,
        ping_everyone: bool = False
    ):
        embed = discord.Embed(title=f"📢  {title}", description=message, color=0x5865F2)
        embed.set_footer(text=f"Announcement by {interaction.user}")

        content = "@everyone" if ping_everyone else None
        await channel.send(content=content, embed=embed)

        await interaction.response.send_message(
            embed=success_embed("Announcement Sent", f"Posted to {channel.mention}."),
            ephemeral=True
        )

    # ── /botstats ─────────────────────────────────────────────
    @app_commands.command(name="botstats", description="Owner: inspect high-level bot statistics.")
    @is_owner()
    async def botstats(self, interaction: discord.Interaction):
        total_members = sum(g.member_count for g in self.bot.guilds)
        total_cmds    = await db.get_total_commands()
        top_cmds      = await db.get_top_commands(5)
        bl_count      = len(await db.get_blacklist())

        embed = discord.Embed(title="📊  Bot Statistics", color=0x5865F2)
        embed.add_field(name="Guilds",      value=f"`{len(self.bot.guilds)}`",   inline=True)
        embed.add_field(name="Users",       value=f"`{total_members:,}`",        inline=True)
        embed.add_field(name="Blacklisted", value=f"`{bl_count}`",               inline=True)
        embed.add_field(name="Commands Run",value=f"`{total_cmds:,}`",           inline=True)
        embed.add_field(name="Latency",     value=f"`{round(self.bot.latency * 1000)} ms`", inline=True)

        if top_cmds:
            top_str = "\n".join(f"`/{c['command']}` — {c['uses']} uses" for c in top_cmds)
            embed.add_field(name="🏆 Top Commands", value=top_str, inline=False)

        guild_list = "\n".join(f"• {g.name} (`{g.id}`) — {g.member_count} members" for g in list(self.bot.guilds)[:10])
        embed.add_field(name=f"📡 Guilds ({len(self.bot.guilds)})", value=guild_list or "none", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /dm ───────────────────────────────────────────────────
    @app_commands.command(name="dm", description="Owner: send a direct message through the bot.")
    @app_commands.describe(user_id="User ID to DM", message="Message content")
    @is_owner()
    async def dm(self, interaction: discord.Interaction, user_id: str, message: str):
        try:
            uid  = int(user_id)
            user = await self.bot.fetch_user(uid)
        except (ValueError, discord.NotFound):
            await interaction.response.send_message(embed=error_embed("Not Found", "Couldn't find that user."), ephemeral=True)
            return

        embed = discord.Embed(
            title="📬  Message from Bot Owner",
            description=message,
            color=0x5865F2
        )
        try:
            await user.send(embed=embed)
            await interaction.response.send_message(
                embed=success_embed("DM Sent", f"Message delivered to `{user}`."),
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=error_embed("DM Failed", "That user has DMs disabled."),
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Owner(bot))
