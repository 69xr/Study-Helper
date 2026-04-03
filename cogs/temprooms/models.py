import discord
import json
from utils import db
from utils.helpers import success_embed, error_embed

REGIONS = [
    ("🌐 Auto",          "auto"),
    ("🇺🇸 US East",      "us-east"),
    ("🇺🇸 US West",      "us-west"),
    ("🇺🇸 US Central",   "us-central"),
    ("🇧🇷 Brazil",       "brazil"),
    ("🇪🇺 Europe",       "europe"),
    ("🇸🇬 Singapore",    "singapore"),
    ("🇦🇺 Sydney",       "sydney"),
    ("🇯🇵 Japan",        "japan"),
    ("🇮🇳 India",        "india"),
    ("🇿🇦 South Africa", "southafrica"),
    ("🇦🇪 Dubai",        "dubai"),
    ("🇳🇴 Rotterdam",    "rotterdam"),
    ("🇷🇺 Russia",       "russia"),
    ("🇰🇷 South Korea",  "south-korea"),
]

PANEL_COLOR = 0x5865F2


async def resolve_room(interaction: discord.Interaction):
    room = await db.get_temp_room(interaction.channel_id)
    if room:
        return room
    return await db.get_user_temp_room(interaction.guild_id, interaction.user.id)


async def check_owner(interaction: discord.Interaction, room: dict) -> bool:
    if room["owner_id"] == interaction.user.id:
        return True
    if interaction.user.guild_permissions.manage_channels:
        return True
    await interaction.response.send_message(
        embed=error_embed("Not Your Room", "Only the room owner can use these controls."),
        ephemeral=True,
    )
    return False


def build_panel_embed(vc: discord.VoiceChannel, owner: discord.Member) -> discord.Embed:
    embed = discord.Embed(
        title="🔊 TempVoice — Room Controls",
        description=(
            f"**Room:** {vc.mention}  •  **Owner:** {owner.mention}\n\n"
            "Use the buttons below to manage your room. "
            "The room is automatically deleted when everyone leaves."
        ),
        color=PANEL_COLOR,
    )
    embed.add_field(
        name="Row 1 — Room Settings",
        value="💬 Topic · ⏳ Wait Room · 🔒 Privacy · 👥 Limit · ✏️ Rename",
        inline=False,
    )
    embed.add_field(
        name="Row 2 — Member Controls",
        value="🌐 Region · 👢 Kick · 📨 Invite · 🚷 Untrust · 🤝 Trust",
        inline=False,
    )
    embed.add_field(
        name="Row 3 — Ownership",
        value="🗑️ Delete · 📤 Transfer · 👑 Take · ✅ Unban · 🚫 Ban",
        inline=False,
    )
    embed.set_footer(text=f"Room ID: {vc.id}")
    return embed


class RenameModal(discord.ui.Modal, title="Rename Your Room"):
    def __init__(self, channel_id: int):
        super().__init__()
        self.channel_id = channel_id

    new_name = discord.ui.TextInput(
        label="New Room Name",
        placeholder="Max 100 characters",
        max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction):
        name = self.new_name.value.strip()
        if not name:
            await interaction.response.send_message(embed=error_embed("Empty Name", "Name cannot be blank."), ephemeral=True)
            return
        vc = interaction.guild.get_channel(self.channel_id)
        if vc:
            await vc.edit(name=name)
        await db.update_temp_room(self.channel_id, name=name)
        await interaction.response.send_message(
            embed=success_embed("✏️ Room Renamed", f"Your room is now called **{name}**."), ephemeral=True
        )


class LimitModal(discord.ui.Modal, title="Set User Limit"):
    def __init__(self, channel_id: int):
        super().__init__()
        self.channel_id = channel_id

    limit = discord.ui.TextInput(
        label="User Limit",
        placeholder="Enter 0 for unlimited, or 1–99",
        max_length=2,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.limit.value)
            if not (0 <= val <= 99):
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                embed=error_embed("Invalid Input", "Enter a number between **0** (unlimited) and **99**."),
                ephemeral=True,
            )
            return
        vc = interaction.guild.get_channel(self.channel_id)
        if vc:
            await vc.edit(user_limit=val)
        await db.update_temp_room(self.channel_id, user_limit=val)
        display = "∞ Unlimited" if val == 0 else f"{val} members"
        await interaction.response.send_message(
            embed=success_embed("👥 Limit Updated", f"Room limit set to **{display}**."), ephemeral=True
        )


class TopicModal(discord.ui.Modal, title="Set Room Topic"):
    def __init__(self, channel_id: int):
        super().__init__()
        self.channel_id = channel_id

    topic = discord.ui.TextInput(
        label="Topic",
        placeholder="What's happening in here?",
        max_length=120,
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        val = self.topic.value.strip()
        vc = interaction.guild.get_channel(self.channel_id)
        if vc:
            try:
                await vc.edit(status=val or None)
            except (discord.HTTPException, AttributeError):
                pass
        msg = f"Topic set to: **{val}**" if val else "Topic has been cleared."
        await interaction.response.send_message(
            embed=success_embed("💬 Topic Updated", msg), ephemeral=True
        )


class KickSelectView(discord.ui.View):
    def __init__(self, channel_id: int, options: list):
        super().__init__(timeout=30)
        self.channel_id = channel_id
        sel = discord.ui.Select(placeholder="Select a member to kick…", options=options)
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction: discord.Interaction):
        uid = int(self.children[0].values[0])
        member = interaction.guild.get_member(uid)
        if member and member.voice and member.voice.channel and member.voice.channel.id == self.channel_id:
            await member.move_to(None, reason=f"Kicked from temp room by {interaction.user}")
        name = member.mention if member else f"`{uid}`"
        await interaction.response.edit_message(
            embed=success_embed("👢 Member Kicked", f"{name} has been removed from the room."), view=None
        )


class BanSelectView(discord.ui.View):
    def __init__(self, channel_id: int, options: list):
        super().__init__(timeout=30)
        self.channel_id = channel_id
        sel = discord.ui.Select(placeholder="Select a member to ban…", options=options)
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction: discord.Interaction):
        uid = int(self.children[0].values[0])
        room = await db.get_temp_room(self.channel_id)
        if room:
            banned = json.loads(room.get("banned_users") or "[]")
            if uid not in banned:
                banned.append(uid)
            await db.update_temp_room(self.channel_id, banned_users=json.dumps(banned))
        vc = interaction.guild.get_channel(self.channel_id)
        member = interaction.guild.get_member(uid)
        if vc and member:
            await vc.set_permissions(member, connect=False, view_channel=False)
        if member and member.voice and member.voice.channel and member.voice.channel.id == self.channel_id:
            await member.move_to(None, reason="Banned from temp room")
        name = member.mention if member else f"`{uid}`"
        await interaction.response.edit_message(
            embed=success_embed("🚫 Member Banned", f"{name} has been banned from this room."), view=None
        )


class UnbanSelectView(discord.ui.View):
    def __init__(self, channel_id: int, options: list):
        super().__init__(timeout=30)
        self.channel_id = channel_id
        sel = discord.ui.Select(placeholder="Select a member to unban…", options=options)
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction: discord.Interaction):
        uid = int(self.children[0].values[0])
        room = await db.get_temp_room(self.channel_id)
        if room:
            banned = json.loads(room.get("banned_users") or "[]")
            banned = [b for b in banned if b != uid]
            await db.update_temp_room(self.channel_id, banned_users=json.dumps(banned))
        vc = interaction.guild.get_channel(self.channel_id)
        member = interaction.guild.get_member(uid)
        if vc and member:
            await vc.set_permissions(member, overwrite=None)
        name = member.mention if member else f"`{uid}`"
        await interaction.response.edit_message(
            embed=success_embed("✅ Member Unbanned", f"{name} can now rejoin the room."), view=None
        )


class TransferSelectView(discord.ui.View):
    def __init__(self, channel_id: int, old_owner_id: int, options: list):
        super().__init__(timeout=30)
        self.channel_id = channel_id
        self.old_owner_id = old_owner_id
        sel = discord.ui.Select(placeholder="Transfer ownership to…", options=options)
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction: discord.Interaction):
        uid = int(self.children[0].values[0])
        member = interaction.guild.get_member(uid)
        vc = interaction.guild.get_channel(self.channel_id)
        if vc:
            old = interaction.guild.get_member(self.old_owner_id)
            if old:
                await vc.set_permissions(old, overwrite=None)
            if member:
                await vc.set_permissions(member, connect=True, manage_channels=True, move_members=True)
        await db.update_temp_room(self.channel_id, owner_id=uid)
        name = member.mention if member else f"`{uid}`"
        await interaction.response.edit_message(
            embed=success_embed("📤 Ownership Transferred", f"Room ownership passed to {name}."), view=None
        )


class TrustSelectView(discord.ui.View):
    def __init__(self, channel_id: int, options: list):
        super().__init__(timeout=30)
        self.channel_id = channel_id
        sel = discord.ui.Select(placeholder="Select a member to trust…", options=options)
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction: discord.Interaction):
        uid = int(self.children[0].values[0])
        member = interaction.guild.get_member(uid)
        vc = interaction.guild.get_channel(self.channel_id)
        if vc and member:
            await vc.set_permissions(member, connect=True, speak=True, view_channel=True)
        name = member.mention if member else f"`{uid}`"
        await interaction.response.edit_message(
            embed=success_embed("🤝 Member Trusted", f"{name} can always join this room."), view=None
        )


class UntrustSelectView(discord.ui.View):
    def __init__(self, channel_id: int, options: list):
        super().__init__(timeout=30)
        self.channel_id = channel_id
        sel = discord.ui.Select(placeholder="Select a member to untrust…", options=options)
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction: discord.Interaction):
        uid = int(self.children[0].values[0])
        member = interaction.guild.get_member(uid)
        vc = interaction.guild.get_channel(self.channel_id)
        if vc and member:
            await vc.set_permissions(member, overwrite=None)
        name = member.mention if member else f"`{uid}`"
        await interaction.response.edit_message(
            embed=success_embed("🚷 Trust Removed", f"Custom permissions for {name} have been cleared."), view=None
        )


class RegionSelectView(discord.ui.View):
    def __init__(self, channel_id: int):
        super().__init__(timeout=30)
        self.channel_id = channel_id
        options = [discord.SelectOption(label=label, value=value) for label, value in REGIONS]
        sel = discord.ui.Select(placeholder="Choose a server region…", options=options)
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction: discord.Interaction):
        raw = self.children[0].values[0]
        rtc_region = None if raw == "auto" else raw
        vc = interaction.guild.get_channel(self.channel_id)
        if vc:
            try:
                await vc.edit(rtc_region=rtc_region)
            except discord.HTTPException:
                await interaction.response.edit_message(
                    embed=error_embed("Region Change Failed", "Discord rejected this region change."), view=None
                )
                return
        label = next((l for l, v in REGIONS if v == raw), raw)
        await interaction.response.edit_message(
            embed=success_embed("🌐 Region Updated", f"Server region set to **{label}**."), view=None
        )


class InviteSelectView(discord.ui.View):
    def __init__(self, channel_id: int, options: list):
        super().__init__(timeout=30)
        self.channel_id = channel_id
        sel = discord.ui.Select(placeholder="Choose a member to invite…", options=options)
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction: discord.Interaction):
        uid = int(self.children[0].values[0])
        member = interaction.guild.get_member(uid)
        vc = interaction.guild.get_channel(self.channel_id)
        if vc and member:
            await vc.set_permissions(member, connect=True, view_channel=True)
        if member:
            try:
                await member.send(embed=discord.Embed(
                    description=(
                        f"📨 **{interaction.user.display_name}** has invited you to their voice room "
                        f"in **{interaction.guild.name}**!\n\nJoin {vc.mention} to hop in."
                    ),
                    color=PANEL_COLOR,
                ))
            except Exception:
                pass
        name = member.mention if member else f"`{uid}`"
        await interaction.response.edit_message(
            embed=success_embed("📨 Invitation Sent", f"{name} has been invited and can now join."), view=None
        )
