import re
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from utils.helpers import base_embed


class ServerInfo(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="server", description="View detailed server information.")
    async def server(self, interaction: discord.Interaction):
        g = interaction.guild
        await g.chunk()

        bots = sum(1 for m in g.members if m.bot)
        humans = g.member_count - bots
        online = sum(1 for m in g.members if m.status != discord.Status.offline)
        created = int(g.created_at.timestamp())
        boosts = g.premium_subscription_count or 0
        boost_bar = "■" * min(boosts, 14) + "·" * max(0, 14 - min(boosts, 14))
        features = [f.replace("_", " ").title() for f in sorted(g.features)[:8]] or ["Standard Server"]

        embed = base_embed(
            title=f"{g.name} | Server Profile",
            description=(
                f"Created <t:{created}:D> and running with **{g.member_count:,} members**, "
                f"**{len(g.roles)} roles**, and **Level {g.premium_tier}** boosting."
            ),
            color=0x5865F2,
        )
        embed.timestamp = datetime.now(timezone.utc)

        if g.icon:
            embed.set_thumbnail(url=g.icon.url)
        if g.banner:
            embed.set_image(url=g.banner.url)

        embed.add_field(
            name="Identity",
            value=(
                f"**Owner:** {g.owner.mention}\n"
                f"**Server ID:** `{g.id}`\n"
                f"**Locale:** `{g.preferred_locale}`"
            ),
            inline=True,
        )
        embed.add_field(
            name="Members",
            value=(
                f"**Total:** `{g.member_count:,}`\n"
                f"**Humans:** `{humans:,}`\n"
                f"**Bots:** `{bots:,}`\n"
                f"**Online:** `{online:,}`"
            ),
            inline=True,
        )
        embed.add_field(
            name="Structure",
            value=(
                f"**Text:** `{len(g.text_channels)}`\n"
                f"**Voice:** `{len(g.voice_channels)}`\n"
                f"**Stage:** `{len(g.stage_channels)}`\n"
                f"**Categories:** `{len(g.categories)}`"
            ),
            inline=True,
        )
        embed.add_field(
            name="Boosting",
            value=(
                f"**Boosts:** `{boosts}`\n"
                f"**Tier:** `Level {g.premium_tier}`\n"
                f"`{boost_bar}`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Server Signals",
            value=(
                f"**Verification:** `{g.verification_level}`\n"
                f"**Content Filter:** `{g.explicit_content_filter}`\n"
                f"**Emojis:** `{len(g.emojis)}/{g.emoji_limit}`\n"
                f"**Stickers:** `{len(g.stickers)}/{g.sticker_limit}`"
            ),
            inline=True,
        )
        embed.add_field(
            name="Extra Surfaces",
            value=(
                f"**Forums:** `{len(getattr(g, 'forums', []))}`\n"
                f"**Scheduled Events:** `{len(g.scheduled_events)}`\n"
                f"**Rules Channel:** {g.rules_channel.mention if g.rules_channel else 'Not set'}\n"
                f"**System Channel:** {g.system_channel.mention if g.system_channel else 'Not set'}"
            ),
            inline=True,
        )
        embed.add_field(
            name="Features",
            value=", ".join(f"`{feature}`" for feature in features),
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="servericon", description="Get the server's icon.")
    async def servericon(self, interaction: discord.Interaction):
        g = interaction.guild
        if not g.icon:
            await interaction.response.send_message(
                embed=discord.Embed(description="This server has no icon.", color=0xED4245),
                ephemeral=True,
            )
            return
        embed = discord.Embed(title=f"{g.name} | Server Icon", color=0x5865F2)
        embed.set_image(url=g.icon.url)
        embed.add_field(
            name="Links",
            value=(
                f"[PNG]({g.icon.with_format('png').url})  •  "
                f"[JPG]({g.icon.with_format('jpg').url})  •  "
                f"[WEBP]({g.icon.with_format('webp').url})"
            ),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="serverbanner", description="Get the server's banner.")
    async def serverbanner(self, interaction: discord.Interaction):
        g = interaction.guild
        if not g.banner:
            await interaction.response.send_message(
                embed=discord.Embed(description="This server has no banner.", color=0xED4245),
                ephemeral=True,
            )
            return
        embed = discord.Embed(title=f"{g.name} | Server Banner", color=0x5865F2)
        embed.set_image(url=g.banner.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="membercount", description="Show member count breakdown.")
    async def membercount(self, interaction: discord.Interaction):
        g = interaction.guild
        await g.chunk()
        humans = sum(1 for m in g.members if not m.bot)
        bots = sum(1 for m in g.members if m.bot)
        online = sum(1 for m in g.members if m.status != discord.Status.offline)
        embed = discord.Embed(title=f"{g.name} | Members", color=0x57F287)
        embed.add_field(name="Total", value=f"`{g.member_count:,}`", inline=True)
        embed.add_field(name="Humans", value=f"`{humans:,}`", inline=True)
        embed.add_field(name="Bots", value=f"`{bots:,}`", inline=True)
        embed.add_field(name="Online", value=f"`{online:,}`", inline=True)
        if g.icon:
            embed.set_thumbnail(url=g.icon.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="roleinfo", description="Get detailed info about a role.")
    @app_commands.describe(role="The role to inspect")
    async def roleinfo(self, interaction: discord.Interaction, role: discord.Role):
        created = int(role.created_at.timestamp())
        members = len(role.members)
        key_perms = []
        if role.permissions.administrator:
            key_perms.append("Administrator")
        if role.permissions.manage_guild:
            key_perms.append("Manage Server")
        if role.permissions.manage_messages:
            key_perms.append("Manage Messages")
        if role.permissions.manage_roles:
            key_perms.append("Manage Roles")
        if role.permissions.kick_members:
            key_perms.append("Kick Members")
        if role.permissions.ban_members:
            key_perms.append("Ban Members")
        if role.permissions.mention_everyone:
            key_perms.append("Mention Everyone")

        embed = discord.Embed(
            title=f"Role: {role.name}",
            color=role.color if role.color.value else 0x5865F2,
        )
        embed.add_field(name="ID", value=f"`{role.id}`", inline=True)
        embed.add_field(name="Color", value=f"`{role.color}`", inline=True)
        embed.add_field(name="Members", value=f"`{members:,}`", inline=True)
        embed.add_field(name="Position", value=f"`{role.position}`", inline=True)
        embed.add_field(name="Mentionable", value="Yes" if role.mentionable else "No", inline=True)
        embed.add_field(name="Hoisted", value="Yes" if role.hoist else "No", inline=True)
        embed.add_field(name="Created", value=f"<t:{created}:D>", inline=False)
        if key_perms:
            embed.add_field(name="Key Permissions", value=", ".join(f"`{p}`" for p in key_perms), inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="emojiinfo", description="Get info about a custom emoji.")
    @app_commands.describe(emoji="The custom emoji to inspect")
    async def emojiinfo(self, interaction: discord.Interaction, emoji: str):
        match = re.search(r"<a?:(\w+):(\d+)>", emoji)
        if not match:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="Please provide a custom server emoji, not a Unicode emoji.",
                    color=0xED4245,
                ),
                ephemeral=True,
            )
            return

        name = match.group(1)
        eid = int(match.group(2))
        is_gif = emoji.startswith("<a:")
        url = f"https://cdn.discordapp.com/emojis/{eid}.{'gif' if is_gif else 'png'}"
        guild_emoji = discord.utils.get(interaction.guild.emojis, id=eid)
        created = int(guild_emoji.created_at.timestamp()) if guild_emoji else None

        embed = discord.Embed(title=f"Emoji: :{name}:", color=0x5865F2)
        embed.set_thumbnail(url=url)
        embed.add_field(name="ID", value=f"`{eid}`", inline=True)
        embed.add_field(name="Name", value=f"`{name}`", inline=True)
        embed.add_field(name="Animated", value="Yes" if is_gif else "No", inline=True)
        if created:
            embed.add_field(name="Created", value=f"<t:{created}:D>", inline=True)
        embed.add_field(name="URL", value=f"[Open]({url})", inline=False)
        embed.add_field(name="Usage", value=f"`<{'a' if is_gif else ''}:{name}:{eid}>`", inline=False)
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(ServerInfo(bot))
