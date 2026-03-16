"""
cogs/info.py
Commands: /server  /userinfo  /roles
"""
import discord
from discord import app_commands
from discord.ext import commands


class Info(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /server ───────────────────────────────────────────────
    @app_commands.command(name="server", description="Display information about this server.")
    async def server(self, interaction: discord.Interaction):
        g = interaction.guild

        humans = sum(1 for m in g.members if not m.bot)
        bots   = g.member_count - humans

        vl_labels = {
            discord.VerificationLevel.none:    "None",
            discord.VerificationLevel.low:     "Low",
            discord.VerificationLevel.medium:  "Medium",
            discord.VerificationLevel.high:    "High",
            discord.VerificationLevel.highest: "Highest",
        }

        embed = discord.Embed(
            title=f"🏠  {g.name}",
            description=g.description or "",
            color=0x5865F2
        )
        if g.icon:
            embed.set_thumbnail(url=g.icon.url)
        if g.banner:
            embed.set_image(url=g.banner.url)

        embed.add_field(name="👑 Owner",      value=g.owner.mention,                                inline=True)
        embed.add_field(name="🆔 ID",         value=f"`{g.id}`",                                   inline=True)
        embed.add_field(name="📅 Created",    value=discord.utils.format_dt(g.created_at, "D"),    inline=True)

        embed.add_field(name="👥 Members",    value=f"{humans} humans • {bots} bots",              inline=True)
        embed.add_field(name="💬 Channels",   value=f"{len(g.text_channels)}T • {len(g.voice_channels)}V • {len(g.categories)}C", inline=True)
        embed.add_field(name="🎭 Roles",      value=len(g.roles) - 1,                              inline=True)

        embed.add_field(name="😀 Emojis",     value=f"{len(g.emojis)}/{g.emoji_limit}",            inline=True)
        embed.add_field(name="🚀 Boost",      value=f"Level {g.premium_tier} ({g.premium_subscription_count} boosts)", inline=True)
        embed.add_field(name="🔒 Verify",     value=vl_labels.get(g.verification_level, "?"),      inline=True)

        embed.set_footer(
            text=f"Requested by {interaction.user}",
            icon_url=interaction.user.display_avatar.url
        )
        await interaction.response.send_message(embed=embed)

    # ── /userinfo ─────────────────────────────────────────────
    @app_commands.command(name="userinfo", description="Display information about a member.")
    @app_commands.describe(user="The member to look up (leave empty for yourself).")
    async def userinfo(self, interaction: discord.Interaction, user: discord.Member = None):
        t = user or interaction.user

        roles = [r for r in reversed(t.roles) if r.name != "@everyone"]
        roles_str = " ".join(r.mention for r in roles[:12])
        if len(roles) > 12:
            roles_str += f" +{len(roles)-12} more"

        badges = []
        if t.bot:                    badges.append("🤖 Bot")
        if t.premium_since:          badges.append("🌟 Booster")
        if t.id == interaction.guild.owner_id:  badges.append("👑 Owner")

        embed = discord.Embed(
            title=f"👤  {t}",
            color=t.color if t.color.value else 0x5865F2
        )
        embed.set_thumbnail(url=t.display_avatar.url)

        embed.add_field(name="🆔 ID",           value=f"`{t.id}`",     inline=True)
        embed.add_field(name="📛 Nick",          value=t.display_name,  inline=True)
        embed.add_field(name="🏷️ Top Role",     value=t.top_role.mention, inline=True)

        embed.add_field(name="📅 Account Created", value=discord.utils.format_dt(t.created_at, "D"),  inline=True)
        embed.add_field(name="📥 Joined Server",   value=discord.utils.format_dt(t.joined_at,  "D"),  inline=True)
        if badges:
            embed.add_field(name="🏅 Badges", value="  ".join(badges), inline=True)

        embed.add_field(name=f"🎭 Roles [{len(roles)}]", value=roles_str or "None", inline=False)
        embed.set_footer(text=f"Requested by {interaction.user}")
        await interaction.response.send_message(embed=embed)

    # ── /roles ────────────────────────────────────────────────
    @app_commands.command(name="roles", description="List all roles in this server.")
    async def roles(self, interaction: discord.Interaction):
        guild  = interaction.guild
        roles  = [r for r in reversed(guild.roles) if r.name != "@everyone"]
        chunks = [roles[i:i+20] for i in range(0, len(roles), 20)]

        embeds = []
        for i, chunk in enumerate(chunks):
            embed = discord.Embed(
                title=f"🎭  Roles — {guild.name} ({len(roles)} total)",
                description="\n".join(
                    f"{r.mention}  •  `{len(r.members)} members`"
                    for r in chunk
                ),
                color=0x5865F2
            )
            embed.set_footer(text=f"Page {i+1}/{len(chunks)}")
            embeds.append(embed)

        await interaction.response.send_message(embed=embeds[0], ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Info(bot))
