import discord
from discord import app_commands
from discord.ext import commands
import json
from utils import db
from utils.helpers import success_embed, error_embed, info_embed
from .models import (
    resolve_room, check_owner, build_panel_embed,
    RenameModal, LimitModal, TopicModal,
    KickSelectView, BanSelectView, UnbanSelectView,
    TransferSelectView, TrustSelectView, UntrustSelectView,
    RegionSelectView, InviteSelectView,
)

temproom_group = app_commands.Group(
    name="temproom",
    description="Manage your temporary voice room.",
)


class TempRoomControls(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _gate(self, interaction: discord.Interaction):
        room = await resolve_room(interaction)
        if not room:
            await interaction.response.send_message(
                embed=error_embed("Room Not Found", "This panel is not linked to an active room."),
                ephemeral=True,
            )
            return None
        if not await check_owner(interaction, room):
            return None
        return room

    @discord.ui.button(label="Topic", emoji="💬", style=discord.ButtonStyle.secondary, custom_id="tr_topic", row=0)
    async def topic_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        room = await self._gate(interaction)
        if room:
            await interaction.response.send_modal(TopicModal(room["channel_id"]))

    @discord.ui.button(label="Wait Room", emoji="⏳", style=discord.ButtonStyle.secondary, custom_id="tr_waitroom", row=0)
    async def waitroom_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        room = await self._gate(interaction)
        if not room:
            return
        vc = interaction.guild.get_channel(room["channel_id"])
        if not vc:
            await interaction.response.send_message(embed=error_embed("Room Not Found"), ephemeral=True)
            return
        current = vc.overwrites_for(interaction.guild.default_role)
        enabling = current.connect is not False
        await vc.set_permissions(interaction.guild.default_role, connect=not enabling, view_channel=True)
        if enabling:
            msg = "Members can see the room but cannot join until you invite them."
            title = "⏳ Wait Room Enabled"
        else:
            msg = "Members can now join the room freely."
            title = "✅ Wait Room Disabled"
        await interaction.response.send_message(embed=success_embed(title, msg), ephemeral=True)

    @discord.ui.button(label="Privacy", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="tr_lock", row=0)
    async def lock_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        room = await self._gate(interaction)
        if not room:
            return
        vc = interaction.guild.get_channel(room["channel_id"])
        if not vc:
            await interaction.response.send_message(embed=error_embed("Room Not Found"), ephemeral=True)
            return
        locking = not bool(room["locked"])
        await vc.set_permissions(interaction.guild.default_role, connect=False if locking else None)
        await db.update_temp_room(room["channel_id"], locked=int(locking))
        if locking:
            embed = success_embed("🔒 Room Locked", "Your room is now private. Only trusted members can join.")
        else:
            embed = success_embed("🔓 Room Unlocked", "Your room is now open to everyone.")
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="Limit", emoji="👥", style=discord.ButtonStyle.secondary, custom_id="tr_limit", row=0)
    async def limit_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        room = await self._gate(interaction)
        if room:
            await interaction.response.send_modal(LimitModal(room["channel_id"]))

    @discord.ui.button(label="Rename", emoji="✏️", style=discord.ButtonStyle.secondary, custom_id="tr_rename", row=0)
    async def rename_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        room = await self._gate(interaction)
        if room:
            await interaction.response.send_modal(RenameModal(room["channel_id"]))

    @discord.ui.button(label="Region", emoji="🌐", style=discord.ButtonStyle.secondary, custom_id="tr_region", row=1)
    async def region_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        room = await self._gate(interaction)
        if room:
            await interaction.response.send_message("Select a server region:", view=RegionSelectView(room["channel_id"]), ephemeral=True)

    @discord.ui.button(label="Kick", emoji="👢", style=discord.ButtonStyle.secondary, custom_id="tr_kick", row=1)
    async def kick_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        room = await self._gate(interaction)
        if not room:
            return
        vc = interaction.guild.get_channel(room["channel_id"])
        options = [
            discord.SelectOption(label=m.display_name, value=str(m.id), description=str(m))
            for m in (vc.members if vc else []) if m.id != room["owner_id"]
        ]
        if not options:
            await interaction.response.send_message(embed=error_embed("Nobody to Kick", "There are no other members in your room."), ephemeral=True)
            return
        await interaction.response.send_message("Select a member to kick:", view=KickSelectView(room["channel_id"], options), ephemeral=True)

    @discord.ui.button(label="Invite", emoji="📨", style=discord.ButtonStyle.success, custom_id="tr_invite", row=1)
    async def invite_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        room = await self._gate(interaction)
        if not room:
            return
        vc = interaction.guild.get_channel(room["channel_id"])
        in_vc = {m.id for m in vc.members} if vc else set()
        options = [
            discord.SelectOption(label=m.display_name, value=str(m.id), description=str(m))
            for m in interaction.guild.members
            if not m.bot and m.id not in in_vc and m.id != interaction.user.id
        ][:25]
        if not options:
            await interaction.response.send_message(embed=error_embed("Nobody to Invite", "No members are available to invite."), ephemeral=True)
            return
        await interaction.response.send_message("Choose a member to invite:", view=InviteSelectView(room["channel_id"], options), ephemeral=True)

    @discord.ui.button(label="Untrust", emoji="🚷", style=discord.ButtonStyle.secondary, custom_id="tr_untrust", row=1)
    async def untrust_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        room = await self._gate(interaction)
        if not room:
            return
        vc = interaction.guild.get_channel(room["channel_id"])
        if not vc:
            await interaction.response.send_message(embed=error_embed("Room Not Found"), ephemeral=True)
            return
        options = [
            discord.SelectOption(label=t.display_name, value=str(t.id), description=str(t))
            for t, ow in vc.overwrites.items()
            if isinstance(t, discord.Member) and t.id != room["owner_id"] and not ow.is_empty()
        ][:25]
        if not options:
            await interaction.response.send_message(embed=error_embed("No Trusted Members", "Nobody has custom permissions in this room."), ephemeral=True)
            return
        await interaction.response.send_message("Remove trust from:", view=UntrustSelectView(room["channel_id"], options), ephemeral=True)

    @discord.ui.button(label="Trust", emoji="🤝", style=discord.ButtonStyle.success, custom_id="tr_trust", row=1)
    async def trust_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        room = await self._gate(interaction)
        if not room:
            return
        vc = interaction.guild.get_channel(room["channel_id"])
        in_vc = {m.id for m in vc.members} if vc else set()
        options = [
            discord.SelectOption(label=m.display_name, value=str(m.id), description=str(m))
            for m in interaction.guild.members
            if not m.bot and m.id != room["owner_id"] and m.id not in in_vc
        ][:25]
        if not options:
            await interaction.response.send_message(embed=error_embed("Nobody to Trust"), ephemeral=True)
            return
        await interaction.response.send_message("Choose a member to trust:", view=TrustSelectView(room["channel_id"], options), ephemeral=True)

    @discord.ui.button(label="Delete", emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="tr_delete", row=2)
    async def delete_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        room = await self._gate(interaction)
        if not room:
            return
        await interaction.response.send_message(
            embed=success_embed("🗑️ Room Deleted", "Your temporary room has been removed."), ephemeral=True
        )
        vc = interaction.guild.get_channel(room["channel_id"])
        if vc:
            try:
                await vc.delete(reason=f"Temp room deleted by {interaction.user}")
            except Exception:
                pass
        await db.delete_temp_room(room["channel_id"])

    @discord.ui.button(label="Transfer", emoji="📤", style=discord.ButtonStyle.primary, custom_id="tr_transfer", row=2)
    async def transfer_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        room = await self._gate(interaction)
        if not room:
            return
        vc = interaction.guild.get_channel(room["channel_id"])
        options = [
            discord.SelectOption(label=m.display_name, value=str(m.id), description=str(m))
            for m in (vc.members if vc else []) if m.id != interaction.user.id
        ]
        if not options:
            await interaction.response.send_message(embed=error_embed("Nobody Else Here", "Nobody else is in the room to transfer to."), ephemeral=True)
            return
        await interaction.response.send_message(
            "Transfer ownership to:",
            view=TransferSelectView(room["channel_id"], room["owner_id"], options),
            ephemeral=True,
        )

    @discord.ui.button(label="Take Ownership", emoji="👑", style=discord.ButtonStyle.primary, custom_id="tr_take", row=2)
    async def take_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        room = await db.get_temp_room(interaction.channel_id)
        if not room:
            await interaction.response.send_message(embed=error_embed("Room Not Found"), ephemeral=True)
            return
        vc = interaction.guild.get_channel(room["channel_id"])
        if not vc:
            await interaction.response.send_message(embed=error_embed("Room Not Found"), ephemeral=True)
            return
        if any(m.id == room["owner_id"] for m in vc.members):
            await interaction.response.send_message(
                embed=error_embed("Owner Still Present", "You can only claim ownership after the current owner has left."),
                ephemeral=True,
            )
            return
        if interaction.user not in vc.members:
            await interaction.response.send_message(
                embed=error_embed("Not in Room", "You must be inside the voice channel to claim ownership."),
                ephemeral=True,
            )
            return
        old = interaction.guild.get_member(room["owner_id"])
        if old:
            await vc.set_permissions(old, overwrite=None)
        await vc.set_permissions(interaction.user, connect=True, manage_channels=True, move_members=True)
        await db.update_temp_room(room["channel_id"], owner_id=interaction.user.id)
        await interaction.response.send_message(
            embed=success_embed("👑 Ownership Claimed", f"{interaction.user.mention} is now the room owner.")
        )

    @discord.ui.button(label="Unban", emoji="✅", style=discord.ButtonStyle.success, custom_id="tr_unban", row=2)
    async def unban_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        room = await self._gate(interaction)
        if not room:
            return
        banned = json.loads(room.get("banned_users") or "[]")
        if not banned:
            await interaction.response.send_message(embed=error_embed("No Bans", "Nobody is currently banned from this room."), ephemeral=True)
            return
        options = []
        for uid in banned[:25]:
            m = interaction.guild.get_member(uid)
            options.append(discord.SelectOption(
                label=m.display_name if m else str(uid),
                value=str(uid),
                description=str(m) if m else "Unknown user",
            ))
        await interaction.response.send_message("Select a member to unban:", view=UnbanSelectView(room["channel_id"], options), ephemeral=True)

    @discord.ui.button(label="Ban", emoji="🚫", style=discord.ButtonStyle.danger, custom_id="tr_ban", row=2)
    async def ban_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        room = await self._gate(interaction)
        if not room:
            return
        vc = interaction.guild.get_channel(room["channel_id"])
        options = [
            discord.SelectOption(label=m.display_name, value=str(m.id), description=str(m))
            for m in (vc.members if vc else []) if m.id != room["owner_id"]
        ]
        if not options:
            await interaction.response.send_message(embed=error_embed("Nobody to Ban", "There are no other members in your room."), ephemeral=True)
            return
        await interaction.response.send_message("Select a member to ban:", view=BanSelectView(room["channel_id"], options), ephemeral=True)


class TempRooms(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(TempRoomControls())

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        guild    = member.guild
        settings = await db.get_temproom_settings(guild.id)

        if not settings.get("enabled") or not settings.get("join_channel"):
            return

        join_ch_id = settings["join_channel"]

        if after.channel and after.channel.id == join_ch_id:
            existing = await db.get_user_temp_room(guild.id, member.id)
            if existing:
                existing_vc = guild.get_channel(existing["channel_id"])
                if existing_vc:
                    try:
                        await member.move_to(existing_vc)
                    except Exception:
                        pass
                    return
                else:
                    await db.delete_temp_room(existing["channel_id"])

            template  = settings.get("name_template") or "{user}'s Room"
            room_name = template.replace("{user}", member.display_name).replace("{guild}", guild.name)
            category  = guild.get_channel(settings["category_id"]) if settings.get("category_id") else after.channel.category
            limit     = settings.get("default_limit") or 0
            bitrate   = settings.get("default_bitrate") or 64000

            try:
                vc = await guild.create_voice_channel(
                    name=room_name, category=category,
                    user_limit=limit, bitrate=min(bitrate, guild.bitrate_limit),
                    reason=f"Temp room for {member}",
                )
                await vc.set_permissions(member, connect=True, manage_channels=True, move_members=True)
                await member.move_to(vc)
                await db.create_temp_room(guild.id, vc.id, member.id, room_name, limit)
                await self._post_panel(vc, member)
            except discord.Forbidden:
                pass

        if before.channel and before.channel.id != join_ch_id and before.channel != after.channel:
            room = await db.get_temp_room(before.channel.id)
            if not room:
                return
            vc = guild.get_channel(before.channel.id)
            if not vc:
                await db.delete_temp_room(before.channel.id)
                return
            if len(vc.members) == 0:
                try:
                    await vc.delete(reason="Temp room empty")
                except Exception:
                    pass
                await db.delete_temp_room(before.channel.id)
            elif room["owner_id"] == member.id and vc.members:
                new_owner = vc.members[0]
                old = guild.get_member(member.id)
                if old:
                    await vc.set_permissions(old, overwrite=None)
                await vc.set_permissions(new_owner, connect=True, manage_channels=True, move_members=True)
                await db.update_temp_room(room["channel_id"], owner_id=new_owner.id)
                try:
                    await vc.send(embed=discord.Embed(
                        description=f"👑 {new_owner.mention} is now the room owner.",
                        color=0xFFAA3D,
                    ))
                except Exception:
                    pass

    async def _post_panel(self, vc: discord.VoiceChannel, owner: discord.Member):
        try:
            await vc.send(embed=build_panel_embed(vc, owner), view=TempRoomControls())
        except Exception:
            pass

    @temproom_group.command(name="setup", description="Configure the temp room system for this server.")
    @app_commands.describe(
        join_channel="Voice channel users join to create a room",
        category="Category where new rooms are created",
        name_template="Room name template — use {user} for the member's name",
        default_limit="Default member limit per room (0 = unlimited)",
        enabled="Enable or disable the entire system",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup(self, interaction: discord.Interaction,
                    join_channel: discord.VoiceChannel = None,
                    category: discord.CategoryChannel = None,
                    name_template: str = None,
                    default_limit: app_commands.Range[int, 0, 99] = None,
                    enabled: bool = None):
        if join_channel:              await db.set_temproom_setting(interaction.guild_id, "join_channel",  join_channel.id)
        if category:                  await db.set_temproom_setting(interaction.guild_id, "category_id",   category.id)
        if name_template:             await db.set_temproom_setting(interaction.guild_id, "name_template", name_template)
        if default_limit is not None: await db.set_temproom_setting(interaction.guild_id, "default_limit", default_limit)
        if enabled is not None:       await db.set_temproom_setting(interaction.guild_id, "enabled",       int(enabled))

        s   = await db.get_temproom_settings(interaction.guild_id)
        jch = interaction.guild.get_channel(s["join_channel"]) if s.get("join_channel") else None
        cat = interaction.guild.get_channel(s["category_id"])  if s.get("category_id")  else None

        embed = success_embed("✅ Temp Rooms Configured", "Members who join the join channel will automatically receive their own private voice room.")
        embed.add_field(name="Status",        value="✅ Enabled" if s["enabled"] else "❌ Disabled", inline=True)
        embed.add_field(name="Join Channel",  value=jch.mention if jch else "*Not set*",             inline=True)
        embed.add_field(name="Category",      value=cat.mention if cat else "*Same as join channel*", inline=True)
        embed.add_field(name="Name Template", value=f"`{s['name_template']}`",                        inline=True)
        embed.add_field(name="Default Limit", value=f"`{'∞' if not s['default_limit'] else s['default_limit']}`", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @temproom_group.command(name="rename", description="Rename your temporary room.")
    @app_commands.describe(name="The new name for your room")
    async def rename(self, interaction: discord.Interaction, name: str):
        room = await db.get_user_temp_room(interaction.guild_id, interaction.user.id)
        if not room:
            await interaction.response.send_message(embed=error_embed("No Room", "You don't currently own a temp room."), ephemeral=True)
            return
        vc = interaction.guild.get_channel(room["channel_id"])
        if vc:
            await vc.edit(name=name)
        await db.update_temp_room(room["channel_id"], name=name)
        await interaction.response.send_message(embed=success_embed("✏️ Room Renamed", f"Your room is now called **{name}**."), ephemeral=True)

    @temproom_group.command(name="limit", description="Set the member limit for your room.")
    @app_commands.describe(limit="Maximum members allowed (0 for unlimited)")
    async def limit(self, interaction: discord.Interaction, limit: app_commands.Range[int, 0, 99]):
        room = await db.get_user_temp_room(interaction.guild_id, interaction.user.id)
        if not room:
            await interaction.response.send_message(embed=error_embed("No Room", "You don't currently own a temp room."), ephemeral=True)
            return
        vc = interaction.guild.get_channel(room["channel_id"])
        if vc:
            await vc.edit(user_limit=limit)
        await db.update_temp_room(room["channel_id"], user_limit=limit)
        display = "∞ Unlimited" if not limit else f"{limit} members"
        await interaction.response.send_message(embed=success_embed("👥 Limit Updated", f"Room limit set to **{display}**."), ephemeral=True)

    @temproom_group.command(name="lock", description="Lock your room so no new members can join.")
    async def lock(self, interaction: discord.Interaction):
        room = await db.get_user_temp_room(interaction.guild_id, interaction.user.id)
        if not room:
            await interaction.response.send_message(embed=error_embed("No Room"), ephemeral=True)
            return
        vc = interaction.guild.get_channel(room["channel_id"])
        if vc:
            await vc.set_permissions(interaction.guild.default_role, connect=False)
        await db.update_temp_room(room["channel_id"], locked=1)
        await interaction.response.send_message(embed=success_embed("🔒 Room Locked", "Your room is now private. Only trusted members can join."), ephemeral=True)

    @temproom_group.command(name="unlock", description="Unlock your room to allow everyone to join.")
    async def unlock(self, interaction: discord.Interaction):
        room = await db.get_user_temp_room(interaction.guild_id, interaction.user.id)
        if not room:
            await interaction.response.send_message(embed=error_embed("No Room"), ephemeral=True)
            return
        vc = interaction.guild.get_channel(room["channel_id"])
        if vc:
            await vc.set_permissions(interaction.guild.default_role, connect=None)
        await db.update_temp_room(room["channel_id"], locked=0)
        await interaction.response.send_message(embed=success_embed("🔓 Room Unlocked", "Your room is now open to everyone."), ephemeral=True)

    @temproom_group.command(name="kick", description="Kick a member from your temporary room.")
    @app_commands.describe(user="The member to kick")
    async def kick(self, interaction: discord.Interaction, user: discord.Member):
        room = await db.get_user_temp_room(interaction.guild_id, interaction.user.id)
        if not room:
            await interaction.response.send_message(embed=error_embed("No Room"), ephemeral=True)
            return
        if user.voice and user.voice.channel and user.voice.channel.id == room["channel_id"]:
            await user.move_to(None)
        await interaction.response.send_message(embed=success_embed("👢 Member Kicked", f"{user.mention} has been removed from the room."), ephemeral=True)

    @temproom_group.command(name="ban", description="Ban a member from rejoining your room.")
    @app_commands.describe(user="The member to ban")
    async def ban(self, interaction: discord.Interaction, user: discord.Member):
        room = await db.get_user_temp_room(interaction.guild_id, interaction.user.id)
        if not room:
            await interaction.response.send_message(embed=error_embed("No Room"), ephemeral=True)
            return
        banned = json.loads(room.get("banned_users") or "[]")
        if user.id not in banned:
            banned.append(user.id)
        await db.update_temp_room(room["channel_id"], banned_users=json.dumps(banned))
        vc = interaction.guild.get_channel(room["channel_id"])
        if vc:
            await vc.set_permissions(user, connect=False, view_channel=False)
        if user.voice and user.voice.channel and user.voice.channel.id == room["channel_id"]:
            await user.move_to(None)
        await interaction.response.send_message(embed=success_embed("🚫 Member Banned", f"{user.mention} has been banned from your room."), ephemeral=True)

    @temproom_group.command(name="unban", description="Remove a ban from your temporary room.")
    @app_commands.describe(user="The member to unban")
    async def unban(self, interaction: discord.Interaction, user: discord.Member):
        room = await db.get_user_temp_room(interaction.guild_id, interaction.user.id)
        if not room:
            await interaction.response.send_message(embed=error_embed("No Room"), ephemeral=True)
            return
        banned = json.loads(room.get("banned_users") or "[]")
        banned = [b for b in banned if b != user.id]
        await db.update_temp_room(room["channel_id"], banned_users=json.dumps(banned))
        vc = interaction.guild.get_channel(room["channel_id"])
        if vc:
            await vc.set_permissions(user, overwrite=None)
        await interaction.response.send_message(embed=success_embed("✅ Member Unbanned", f"{user.mention} can now rejoin your room."), ephemeral=True)

    @temproom_group.command(name="transfer", description="Transfer room ownership to another member.")
    @app_commands.describe(user="The member to hand ownership to")
    async def transfer(self, interaction: discord.Interaction, user: discord.Member):
        room = await db.get_user_temp_room(interaction.guild_id, interaction.user.id)
        if not room:
            await interaction.response.send_message(embed=error_embed("No Room"), ephemeral=True)
            return
        vc = interaction.guild.get_channel(room["channel_id"])
        if vc:
            await vc.set_permissions(interaction.user, overwrite=None)
            await vc.set_permissions(user, connect=True, manage_channels=True, move_members=True)
        await db.update_temp_room(room["channel_id"], owner_id=user.id)
        await interaction.response.send_message(embed=success_embed("📤 Ownership Transferred", f"Room ownership has been passed to {user.mention}."))

    @temproom_group.command(name="delete", description="Permanently delete your temporary room.")
    async def delete(self, interaction: discord.Interaction):
        room = await db.get_user_temp_room(interaction.guild_id, interaction.user.id)
        if not room:
            await interaction.response.send_message(embed=error_embed("No Room"), ephemeral=True)
            return
        await interaction.response.send_message(embed=success_embed("🗑️ Room Deleted", "Your temporary room has been removed."), ephemeral=True)
        vc = interaction.guild.get_channel(room["channel_id"])
        if vc:
            try:
                await vc.delete(reason="Owner deleted their temp room")
            except Exception:
                pass
        await db.delete_temp_room(room["channel_id"])

    @temproom_group.command(name="info", description="View details about your current temporary room.")
    async def info(self, interaction: discord.Interaction):
        room = await db.get_user_temp_room(interaction.guild_id, interaction.user.id)
        if not room:
            await interaction.response.send_message(embed=error_embed("No Room", "You don't currently own a temp room."), ephemeral=True)
            return
        vc     = interaction.guild.get_channel(room["channel_id"])
        banned = json.loads(room.get("banned_users") or "[]")
        embed  = info_embed("🔊 Your Room", f"Details for **{room['name']}**.")
        embed.add_field(name="Channel",  value=vc.mention if vc else "`deleted`",                                   inline=True)
        embed.add_field(name="Members",  value=f"`{len(vc.members) if vc else 0}`",                                 inline=True)
        embed.add_field(name="Limit",    value=f"`{'∞' if not room['user_limit'] else room['user_limit']}`",        inline=True)
        embed.add_field(name="Status",   value="🔒 Locked" if room["locked"] else "🔓 Open",                        inline=True)
        embed.add_field(name="Banned",   value=f"`{len(banned)}` member(s)",                                        inline=True)
        embed.add_field(name="Created",  value=f"`{room['created_at'][:16]}`",                                      inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=error_embed("Missing Permissions", "You don't have permission to use this command."), ephemeral=True)


async def setup(bot: commands.Bot):
    bot.tree.add_command(temproom_group)
    await bot.add_cog(TempRooms(bot))
