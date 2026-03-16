import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone

class UserInfo(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="userinfo", description="Get detailed information about a user.")
    @app_commands.describe(user="User to inspect (default: yourself)")
    async def userinfo(self, interaction: discord.Interaction, user: discord.Member = None):
        target  = user or interaction.user
        created = int(target.created_at.timestamp())
        joined  = int(target.joined_at.timestamp()) if target.joined_at else None
        roles   = [r.mention for r in reversed(target.roles) if r != interaction.guild.default_role]

        badges = []
        if target.bot:                                         badges.append("🤖 Bot")
        if target.public_flags.staff:                         badges.append("👮 Discord Staff")
        if target.public_flags.partner:                       badges.append("🤝 Partner")
        if target.public_flags.hypesquad:                     badges.append("🏠 HypeSquad")
        if target.public_flags.bug_hunter:                    badges.append("🐛 Bug Hunter")
        if target.public_flags.verified_bot_developer:        badges.append("🛠️ Dev")
        if target.premium_since:                              badges.append("💎 Nitro Booster")

        embed = discord.Embed(
            title=f"👤 {target.display_name}",
            color=target.color if target.color.value else 0x5865F2,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Username",    value=f"`{target}`",                              inline=True)
        embed.add_field(name="ID",          value=f"`{target.id}`",                           inline=True)
        embed.add_field(name="Status",      value=str(target.status).title(),                 inline=True)
        embed.add_field(name="Account Created", value=f"<t:{created}:D> (<t:{created}:R>)",  inline=False)
        if joined:
            embed.add_field(name="Joined Server",  value=f"<t:{joined}:D> (<t:{joined}:R>)", inline=False)
        if badges:
            embed.add_field(name="Badges",  value=" · ".join(badges),                        inline=False)
        if roles:
            roles_str = " ".join(roles[:15])
            if len(roles) > 15: roles_str += f" +{len(roles)-15} more"
            embed.add_field(name=f"Roles ({len(roles)})", value=roles_str,                   inline=False)
        if target.premium_since:
            boost_ts = int(target.premium_since.timestamp())
            embed.add_field(name="Boosting Since", value=f"<t:{boost_ts}:D>",               inline=True)
        embed.set_footer(text=f"Requested by {interaction.user}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="roles", description="List all server roles with member counts.")
    async def roles(self, interaction: discord.Interaction):
        guild_roles = [r for r in reversed(interaction.guild.roles) if r != interaction.guild.default_role]
        if not guild_roles:
            await interaction.response.send_message(
                embed=discord.Embed(description="No roles found.", color=0xED4245), ephemeral=True)
            return
        lines = [f"{r.mention} — `{len(r.members)}` members" for r in guild_roles[:25]]
        if len(guild_roles) > 25:
            lines.append(f"... and {len(guild_roles)-25} more roles")
        embed = discord.Embed(
            title=f"🎭 {interaction.guild.name} — Roles ({len(guild_roles)})",
            description="\n".join(lines),
            color=0x5865F2
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot): await bot.add_cog(UserInfo(bot))
