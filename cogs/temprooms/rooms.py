"""
cogs/temprooms.py
Events  : on_voice_state_update — detects join/leave for temp room management
Commands: /temproom setup  /temproom rename  /temproom limit  /temproom lock
          /temproom unlock  /temproom kick  /temproom ban  /temproom unban
          /temproom transfer  /temproom delete  /temproom info
"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
import json
from utils import db
from utils.helpers import success_embed, error_embed

temproom_group = app_commands.Group(name="temproom", description="Manage your temporary voice room.")


# ══════════════════════════════════════════════════════════
#  CONTROL PANEL VIEW
# ══════════════════════════════════════════════════════════

class TempRoomControls(discord.ui.View):
    """Persistent control panel posted in the room's companion text channel."""
    def __init__(self):
        super().__init__(timeout=None)

    async def _get_room_and_check(self, interaction: discord.Interaction):
        """Get room data and verify the interacting user is the owner."""
        room = await db.get_temp_room(interaction.channel.id)
        if not room:
            # Try to find by linked voice channel — the panel may be in a text companion
            # For now, we store panel in the VC itself via thread or message
            await interaction.response.send_message(
                embed=error_embed("Not a Temp Room", "This control panel is not linked to an active room."),
                ephemeral=True)
            return None
        if room["owner_id"] != interaction.user.id:
            # Allow if user has Manage Channels
            if not interaction.user.guild_permissions.manage_channels:
                await interaction.response.send_message(
                    embed=error_embed("Not Your Room", "Only the room owner can use these controls."),
                    ephemeral=True)
                return None
        return room

    @discord.ui.button(label="Lock", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="tr_lock", row=0)
    async def lock_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self._get_room_and_check(interaction)
        if not room: return
        vc = interaction.guild.get_channel(room["channel_id"])
        if not vc:
            await interaction.response.send_message(embed=error_embed("Room not found."), ephemeral=True)
            return
        locked = not bool(room["locked"])
        # Toggle connect permission for @everyone
        await vc.set_permissions(interaction.guild.default_role, connect=not locked)
        await db.update_temp_room(room["channel_id"], locked=int(locked))
        action = "🔒 Locked" if locked else "🔓 Unlocked"
        embed = discord.Embed(description=f"{action} by {interaction.user.mention}", color=0xED4245 if locked else 0x57F287)
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="Rename", emoji="✏️", style=discord.ButtonStyle.secondary, custom_id="tr_rename", row=0)
    async def rename_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self._get_room_and_check(interaction)
        if not room: return
        await interaction.response.send_modal(RenameModal(room["channel_id"]))

    @discord.ui.button(label="Limit", emoji="👥", style=discord.ButtonStyle.secondary, custom_id="tr_limit", row=0)
    async def limit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self._get_room_and_check(interaction)
        if not room: return
        await interaction.response.send_modal(LimitModal(room["channel_id"]))

    @discord.ui.button(label="Kick User", emoji="👢", style=discord.ButtonStyle.secondary, custom_id="tr_kick", row=1)
    async def kick_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self._get_room_and_check(interaction)
        if not room: return
        vc = interaction.guild.get_channel(room["channel_id"])
        if not vc or not vc.members:
            await interaction.response.send_message(embed=error_embed("Room is empty."), ephemeral=True)
            return
        options = [
            discord.SelectOption(label=m.display_name, value=str(m.id), description=str(m))
            for m in vc.members if m.id != room["owner_id"]
        ]
        if not options:
            await interaction.response.send_message(embed=error_embed("No one to kick."), ephemeral=True)
            return
        view = KickSelectView(room["channel_id"], options)
        await interaction.response.send_message("Select a user to kick:", view=view, ephemeral=True)

    @discord.ui.button(label="Ban User", emoji="🚫", style=discord.ButtonStyle.danger, custom_id="tr_ban", row=1)
    async def ban_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self._get_room_and_check(interaction)
        if not room: return
        vc = interaction.guild.get_channel(room["channel_id"])
        if not vc:
            await interaction.response.send_message(embed=error_embed("Room not found."), ephemeral=True)
            return
        # Show all VC members + recently left (only show current members for simplicity)
        options = [
            discord.SelectOption(label=m.display_name, value=str(m.id), description=str(m))
            for m in vc.members if m.id != room["owner_id"]
        ]
        if not options:
            await interaction.response.send_message(embed=error_embed("No members to ban."), ephemeral=True)
            return
        view = BanSelectView(room["channel_id"], options)
        await interaction.response.send_message("Select a user to ban from this room:", view=view, ephemeral=True)

    @discord.ui.button(label="Transfer", emoji="👑", style=discord.ButtonStyle.primary, custom_id="tr_transfer", row=1)
    async def transfer_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self._get_room_and_check(interaction)
        if not room: return
        vc = interaction.guild.get_channel(room["channel_id"])
        if not vc:
            await interaction.response.send_message(embed=error_embed("Room not found."), ephemeral=True)
            return
        options = [
            discord.SelectOption(label=m.display_name, value=str(m.id), description=str(m))
            for m in vc.members if m.id != interaction.user.id
        ]
        if not options:
            await interaction.response.send_message(embed=error_embed("Nobody else is in the room."), ephemeral=True)
            return
        view = TransferSelectView(room["channel_id"], options)
        await interaction.response.send_message("Transfer ownership to:", view=view, ephemeral=True)

    @discord.ui.button(label="Delete", emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="tr_delete", row=2)
    async def delete_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self._get_room_and_check(interaction)
        if not room: return
        # Respond FIRST before deleting the channel — otherwise the channel is gone
        # and Discord returns 404 when we try to send the response.
        await interaction.response.send_message(
            embed=success_embed("Room Deleted", "Your temporary room has been removed."),
            ephemeral=True)
        vc = interaction.guild.get_channel(room["channel_id"])
        if vc:
            try:
                await vc.delete(reason=f"Temp room deleted by {interaction.user}")
            except Exception:
                pass
        await db.delete_temp_room(room["channel_id"])

    @discord.ui.button(label="Info", emoji="ℹ️", style=discord.ButtonStyle.secondary, custom_id="tr_info", row=2)
    async def info_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await db.get_temp_room(interaction.channel.id)
        if not room:
            await interaction.response.send_message(embed=error_embed("Room not found."), ephemeral=True)
            return
        vc = interaction.guild.get_channel(room["channel_id"])
        owner = interaction.guild.get_member(room["owner_id"])
        banned = json.loads(room.get("banned_users") or "[]")
        embed = discord.Embed(title="🔊 Room Info", color=0x3d8bff)
        embed.add_field(name="Owner",     value=owner.mention if owner else f"`{room['owner_id']}`", inline=True)
        embed.add_field(name="Members",   value=f"`{len(vc.members) if vc else 0}`",                  inline=True)
        embed.add_field(name="Limit",     value=f"`{room['user_limit'] or '∞'}`",                     inline=True)
        embed.add_field(name="Status",    value="🔒 Locked" if room["locked"] else "🔓 Open",          inline=True)
        embed.add_field(name="Banned",    value=f"`{len(banned)}` user(s)",                           inline=True)
        embed.add_field(name="Created",   value=f"`{room['created_at'][:16]}`",                       inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ── Modals ────────────────────────────────────────────────

class RenameModal(discord.ui.Modal, title="Rename Your Room"):
    def __init__(self, channel_id: int):
        super().__init__()
        self.channel_id = channel_id

    new_name = discord.ui.TextInput(
        label="New Room Name",
        placeholder="Enter a name (max 100 chars)",
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        name = self.new_name.value.strip()
        if not name:
            await interaction.response.send_message(embed=error_embed("Empty name."), ephemeral=True)
            return
        vc = interaction.guild.get_channel(self.channel_id)
        if vc:
            await vc.edit(name=name)
        await db.update_temp_room(self.channel_id, name=name)
        await interaction.response.send_message(
            embed=success_embed("Renamed", f"Room renamed to **{name}**."), ephemeral=True)


class LimitModal(discord.ui.Modal, title="Set User Limit"):
    def __init__(self, channel_id: int):
        super().__init__()
        self.channel_id = channel_id

    limit = discord.ui.TextInput(
        label="User Limit (0 = unlimited)",
        placeholder="Enter a number between 0 and 99",
        max_length=2
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.limit.value)
            if val < 0 or val > 99: raise ValueError
        except ValueError:
            await interaction.response.send_message(
                embed=error_embed("Invalid", "Enter a number between 0 and 99."), ephemeral=True)
            return
        vc = interaction.guild.get_channel(self.channel_id)
        if vc:
            await vc.edit(user_limit=val)
        await db.update_temp_room(self.channel_id, user_limit=val)
        await interaction.response.send_message(
            embed=success_embed("Limit Set", f"Room limit set to `{'∞' if val == 0 else val}`."), ephemeral=True)


# ── Select Views ──────────────────────────────────────────

class KickSelectView(discord.ui.View):
    def __init__(self, channel_id: int, options: list):
        super().__init__(timeout=30)
        self.channel_id = channel_id
        select = discord.ui.Select(placeholder="Choose a user to kick...", options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        uid = int(self.children[0].values[0])
        member = interaction.guild.get_member(uid)
        if member and member.voice and member.voice.channel and member.voice.channel.id == self.channel_id:
            await member.move_to(None, reason=f"Kicked from temp room by {interaction.user}")
        await interaction.response.edit_message(
            embed=success_embed("Kicked", f"{member.mention if member else uid} has been removed."),
            view=None)


class BanSelectView(discord.ui.View):
    def __init__(self, channel_id: int, options: list):
        super().__init__(timeout=30)
        self.channel_id = channel_id
        select = discord.ui.Select(placeholder="Choose a user to ban...", options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        uid  = int(self.children[0].values[0])
        room = await db.get_temp_room(self.channel_id)
        if room:
            banned = json.loads(room.get("banned_users") or "[]")
            if uid not in banned:
                banned.append(uid)
            await db.update_temp_room(self.channel_id, banned_users=json.dumps(banned))
        vc     = interaction.guild.get_channel(self.channel_id)
        member = interaction.guild.get_member(uid)
        if vc:
            await vc.set_permissions(member, connect=False, view_channel=False)
        if member and member.voice and member.voice.channel and member.voice.channel.id == self.channel_id:
            await member.move_to(None, reason="Banned from temp room")
        await interaction.response.edit_message(
            embed=success_embed("Banned", f"{member.mention if member else uid} banned from this room."),
            view=None)


class TransferSelectView(discord.ui.View):
    def __init__(self, channel_id: int, options: list):
        super().__init__(timeout=30)
        self.channel_id = channel_id
        select = discord.ui.Select(placeholder="Transfer ownership to...", options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        uid    = int(self.children[0].values[0])
        member = interaction.guild.get_member(uid)
        await db.update_temp_room(self.channel_id, owner_id=uid)
        await interaction.response.edit_message(
            embed=success_embed("Transferred", f"Room ownership transferred to {member.mention if member else uid}."),
            view=None)


# ══════════════════════════════════════════════════════════
#  COG
# ══════════════════════════════════════════════════════════

class TempRooms(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(TempRoomControls())

    # ── Voice state handler ───────────────────────────────
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member,
                                     before: discord.VoiceState,
                                     after: discord.VoiceState):
        guild = member.guild
        settings = await db.get_temproom_settings(guild.id)

        if not settings.get("enabled") or not settings.get("join_channel"):
            return

        join_ch_id = settings["join_channel"]

        # ── User joined the "Join to Create" channel ──────
        if after.channel and after.channel.id == join_ch_id:
            # Check if user already owns a room
            existing = await db.get_user_temp_room(guild.id, member.id)
            if existing:
                # Move them to their existing room
                existing_vc = guild.get_channel(existing["channel_id"])
                if existing_vc:
                    try:
                        await member.move_to(existing_vc)
                    except Exception:
                        pass
                    return
                else:
                    await db.delete_temp_room(existing["channel_id"])

            # Create the room
            template  = settings.get("name_template") or "{user}'s Room"
            room_name = template.replace("{user}", member.display_name).replace("{guild}", guild.name)
            category  = guild.get_channel(settings["category_id"]) if settings.get("category_id") else after.channel.category
            limit     = settings.get("default_limit") or 0
            bitrate   = settings.get("default_bitrate") or 64000

            try:
                vc = await guild.create_voice_channel(
                    name=room_name,
                    category=category,
                    user_limit=limit,
                    bitrate=min(bitrate, guild.bitrate_limit),
                    reason=f"Temp room for {member}"
                )
                # Give owner full perms
                await vc.set_permissions(member, connect=True, manage_channels=True, move_members=True)
                # Move member in
                await member.move_to(vc)
                # Save to DB
                await db.create_temp_room(guild.id, vc.id, member.id, room_name, limit)
                # Post control panel
                await self._post_control_panel(vc, member, settings)
            except discord.Forbidden:
                pass

        # ── User left a temp room ─────────────────────────
        if before.channel and before.channel.id != join_ch_id:
            room = await db.get_temp_room(before.channel.id)
            if not room:
                return
            vc = guild.get_channel(before.channel.id)
            if vc and len(vc.members) == 0:
                # Delete empty room
                try:
                    await vc.delete(reason="Temp room empty")
                except Exception:
                    pass
                await db.delete_temp_room(before.channel.id)
            elif vc and before.channel.id in [v.id for v in guild.voice_channels]:
                # If owner left, transfer to next person
                if room["owner_id"] == member.id and vc.members:
                    new_owner = vc.members[0]
                    await db.update_temp_room(room["channel_id"], owner_id=new_owner.id)
                    try:
                        await vc.send(
                            embed=discord.Embed(
                                description=f"👑 {new_owner.mention} is now the room owner.",
                                color=0xffaa3d
                            )
                        )
                    except Exception:
                        pass

    async def _post_control_panel(self, vc: discord.VoiceChannel, owner: discord.Member, settings: dict):
        """Post a control panel message inside the voice channel itself (as a text message in the VC)."""
        embed = discord.Embed(
            title="🔊 Your Temporary Room",
            description=(
                f"**Room:** {vc.mention}\n"
                f"**Owner:** {owner.mention}\n\n"
                f"Use the buttons below to control your room.\n"
                f"The room is **automatically deleted** when everyone leaves."
            ),
            color=0x3d8bff
        )
        embed.set_footer(text=f"Room ID: {vc.id}")
        try:
            await vc.send(embed=embed, view=TempRoomControls())
        except Exception:
            pass

    # ══════════════════════════════════════════════════════
    #  SLASH COMMANDS
    # ══════════════════════════════════════════════════════

    @temproom_group.command(name="setup", description="Configure the temp room system.")
    @app_commands.describe(
        join_channel="The voice channel users join to create a room",
        category="Category where rooms are created",
        name_template="Room name template. Use {user} for username",
        default_limit="Default user limit (0 = unlimited)",
        enabled="Enable or disable the system"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup(self, interaction: discord.Interaction,
                    join_channel: discord.VoiceChannel = None,
                    category: discord.CategoryChannel = None,
                    name_template: str = None,
                    default_limit: app_commands.Range[int, 0, 99] = None,
                    enabled: bool = None):
        if join_channel:  await db.set_temproom_setting(interaction.guild_id, "join_channel",  join_channel.id)
        if category:      await db.set_temproom_setting(interaction.guild_id, "category_id",   category.id)
        if name_template: await db.set_temproom_setting(interaction.guild_id, "name_template", name_template)
        if default_limit is not None: await db.set_temproom_setting(interaction.guild_id, "default_limit", default_limit)
        if enabled is not None: await db.set_temproom_setting(interaction.guild_id, "enabled", int(enabled))

        s   = await db.get_temproom_settings(interaction.guild_id)
        jch = interaction.guild.get_channel(s["join_channel"]) if s.get("join_channel") else None
        cat = interaction.guild.get_channel(s["category_id"])  if s.get("category_id") else None
        embed = success_embed("Temp Rooms Configured")
        embed.add_field(name="Status",         value="✅ Enabled" if s["enabled"] else "❌ Disabled", inline=True)
        embed.add_field(name="Join Channel",   value=jch.mention if jch else "Not set",               inline=True)
        embed.add_field(name="Category",       value=cat.mention if cat else "Same as join channel",  inline=True)
        embed.add_field(name="Name Template",  value=f"`{s['name_template']}`",                       inline=True)
        embed.add_field(name="Default Limit",  value=f"`{'∞' if not s['default_limit'] else s['default_limit']}`", inline=True)
        embed.description = "Users who join the **Join Channel** will automatically get their own private voice room."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @temproom_group.command(name="rename", description="Rename your temp room.")
    @app_commands.describe(name="New name for your room")
    async def rename(self, interaction: discord.Interaction, name: str):
        room = await db.get_user_temp_room(interaction.guild_id, interaction.user.id)
        if not room:
            await interaction.response.send_message(embed=error_embed("No Room", "You don't own a temp room."), ephemeral=True)
            return
        vc = interaction.guild.get_channel(room["channel_id"])
        if vc: await vc.edit(name=name)
        await db.update_temp_room(room["channel_id"], name=name)
        await interaction.response.send_message(embed=success_embed("Renamed", f"Room renamed to **{name}**."), ephemeral=True)

    @temproom_group.command(name="limit", description="Set the user limit of your room.")
    @app_commands.describe(limit="Max users (0 = unlimited)")
    async def limit(self, interaction: discord.Interaction, limit: app_commands.Range[int, 0, 99]):
        room = await db.get_user_temp_room(interaction.guild_id, interaction.user.id)
        if not room:
            await interaction.response.send_message(embed=error_embed("No Room", "You don't own a temp room."), ephemeral=True)
            return
        vc = interaction.guild.get_channel(room["channel_id"])
        if vc: await vc.edit(user_limit=limit)
        await db.update_temp_room(room["channel_id"], user_limit=limit)
        await interaction.response.send_message(embed=success_embed("Limit Set", f"Room limit: `{'∞' if not limit else limit}`"), ephemeral=True)

    @temproom_group.command(name="lock", description="Lock your room so nobody new can join.")
    async def lock(self, interaction: discord.Interaction):
        room = await db.get_user_temp_room(interaction.guild_id, interaction.user.id)
        if not room:
            await interaction.response.send_message(embed=error_embed("No Room"), ephemeral=True)
            return
        vc = interaction.guild.get_channel(room["channel_id"])
        if vc: await vc.set_permissions(interaction.guild.default_role, connect=False)
        await db.update_temp_room(room["channel_id"], locked=1)
        await interaction.response.send_message(embed=success_embed("🔒 Locked", "Your room is now private."), ephemeral=True)

    @temproom_group.command(name="unlock", description="Unlock your room to allow new members.")
    async def unlock(self, interaction: discord.Interaction):
        room = await db.get_user_temp_room(interaction.guild_id, interaction.user.id)
        if not room:
            await interaction.response.send_message(embed=error_embed("No Room"), ephemeral=True)
            return
        vc = interaction.guild.get_channel(room["channel_id"])
        if vc: await vc.set_permissions(interaction.guild.default_role, connect=None)
        await db.update_temp_room(room["channel_id"], locked=0)
        await interaction.response.send_message(embed=success_embed("🔓 Unlocked", "Your room is now open."), ephemeral=True)

    @temproom_group.command(name="kick", description="Kick a user from your temp room.")
    @app_commands.describe(user="User to kick")
    async def kick(self, interaction: discord.Interaction, user: discord.Member):
        room = await db.get_user_temp_room(interaction.guild_id, interaction.user.id)
        if not room:
            await interaction.response.send_message(embed=error_embed("No Room"), ephemeral=True)
            return
        if user.voice and user.voice.channel and user.voice.channel.id == room["channel_id"]:
            await user.move_to(None)
        await interaction.response.send_message(embed=success_embed("Kicked", f"{user.mention} removed from the room."), ephemeral=True)

    @temproom_group.command(name="ban", description="Ban a user from your temp room.")
    @app_commands.describe(user="User to ban from re-entering")
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
        if vc: await vc.set_permissions(user, connect=False, view_channel=False)
        if user.voice and user.voice.channel and user.voice.channel.id == room["channel_id"]:
            await user.move_to(None)
        await interaction.response.send_message(embed=success_embed("Banned", f"{user.mention} banned from your room."), ephemeral=True)

    @temproom_group.command(name="unban", description="Unban a user from your temp room.")
    @app_commands.describe(user="User to unban")
    async def unban(self, interaction: discord.Interaction, user: discord.Member):
        room = await db.get_user_temp_room(interaction.guild_id, interaction.user.id)
        if not room:
            await interaction.response.send_message(embed=error_embed("No Room"), ephemeral=True)
            return
        banned = json.loads(room.get("banned_users") or "[]")
        if user.id in banned:
            banned.remove(user.id)
        await db.update_temp_room(room["channel_id"], banned_users=json.dumps(banned))
        vc = interaction.guild.get_channel(room["channel_id"])
        if vc: await vc.set_permissions(user, overwrite=None)
        await interaction.response.send_message(embed=success_embed("Unbanned", f"{user.mention} can now join your room."), ephemeral=True)

    @temproom_group.command(name="transfer", description="Transfer room ownership to someone else.")
    @app_commands.describe(user="New room owner")
    async def transfer(self, interaction: discord.Interaction, user: discord.Member):
        room = await db.get_user_temp_room(interaction.guild_id, interaction.user.id)
        if not room:
            await interaction.response.send_message(embed=error_embed("No Room"), ephemeral=True)
            return
        await db.update_temp_room(room["channel_id"], owner_id=user.id)
        await interaction.response.send_message(embed=success_embed("Transferred", f"Room transferred to {user.mention}."))

    @temproom_group.command(name="delete", description="Delete your temp room.")
    async def delete(self, interaction: discord.Interaction):
        room = await db.get_user_temp_room(interaction.guild_id, interaction.user.id)
        if not room:
            await interaction.response.send_message(embed=error_embed("No Room"), ephemeral=True)
            return
        # Respond first, then delete — channel deletion invalidates the interaction token
        await interaction.response.send_message(embed=success_embed("Deleted", "Your room has been removed."), ephemeral=True)
        vc = interaction.guild.get_channel(room["channel_id"])
        if vc:
            try: await vc.delete(reason="Owner deleted temp room")
            except: pass
        await db.delete_temp_room(room["channel_id"])

    @temproom_group.command(name="info", description="View info about your temp room.")
    async def info(self, interaction: discord.Interaction):
        room = await db.get_user_temp_room(interaction.guild_id, interaction.user.id)
        if not room:
            await interaction.response.send_message(embed=error_embed("No Room", "You don't own a temp room right now."), ephemeral=True)
            return
        vc     = interaction.guild.get_channel(room["channel_id"])
        banned = json.loads(room.get("banned_users") or "[]")
        embed  = discord.Embed(title="🔊 Your Room", color=0x3d8bff)
        embed.add_field(name="Channel",  value=vc.mention if vc else "`deleted`",          inline=True)
        embed.add_field(name="Name",     value=f"`{room['name']}`",                         inline=True)
        embed.add_field(name="Members",  value=f"`{len(vc.members) if vc else 0}`",         inline=True)
        embed.add_field(name="Limit",    value=f"`{'∞' if not room['user_limit'] else room['user_limit']}`", inline=True)
        embed.add_field(name="Status",   value="🔒 Locked" if room["locked"] else "🔓 Open", inline=True)
        embed.add_field(name="Banned",   value=f"`{len(banned)}` user(s)",                  inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=error_embed("Missing Permissions"), ephemeral=True)


async def setup(bot: commands.Bot):
    bot.tree.add_command(temproom_group)
    await bot.add_cog(TempRooms(bot))
