"""
cogs/roles.py
Role panel views — panel creation is handled by the dashboard

FIX: AppCommandChannel.resolve() is called to get a real TextChannel before .send()
"""
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional
from utils import db
from utils.helpers import success_embed, error_embed, parse_hex_color


# ═══════════════════════════════════════════════════════════════
#  PERSISTENT ROLE BUTTON  (custom_id encodes role_id)
# ═══════════════════════════════════════════════════════════════

STYLE_MAP = {
    1: discord.ButtonStyle.primary,
    2: discord.ButtonStyle.success,
    3: discord.ButtonStyle.danger,
    4: discord.ButtonStyle.secondary,
}
STYLE_CYCLE = [
    discord.ButtonStyle.primary,
    discord.ButtonStyle.success,
    discord.ButtonStyle.danger,
    discord.ButtonStyle.secondary,
]


class RoleButton(discord.ui.Button):
    def __init__(self, role_id: int, label: str, emoji: Optional[str], style: int):
        super().__init__(
            label=label,
            emoji=emoji or None,
            style=STYLE_MAP.get(style, discord.ButtonStyle.primary),
            custom_id=f"rolepanel_toggle_{role_id}",
        )
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if role is None:
            await interaction.response.send_message("❌ That role no longer exists.", ephemeral=True)
            return

        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                "❌ I can't assign that role (it's above my top role).", ephemeral=True
            )
            return

        member: discord.Member = interaction.user   # type: ignore
        if role in member.roles:
            await member.remove_roles(role, reason="Self-role panel")
            await interaction.response.send_message(
                f"🔴  Removed **{role.name}** from you.", ephemeral=True
            )
        else:
            await member.add_roles(role, reason="Self-role panel")
            await interaction.response.send_message(
                f"🟢  Added **{role.name}** to you!", ephemeral=True
            )


# ═══════════════════════════════════════════════════════════════
#  PERSISTENT VIEW  (built from DB entries or fresh role objects)
# ═══════════════════════════════════════════════════════════════

class RolePickerView(discord.ui.View):
    """
    Accepts either:
      - list[dict]  — from DB restore: {"role_id", "emoji", "style"}
      - list[tuple] — from fresh creation: (discord.Role, emoji_str, style_int)
    """

    def __init__(self, entries):
        super().__init__(timeout=None)
        for entry in entries:
            if isinstance(entry, dict):
                # DB restore path — label will be filled in properly when the bot
                # has guild context. Use stored label if available, else fall back
                # to a humanised placeholder (role name resolved in button callback).
                self.add_item(RoleButton(
                    role_id=entry["role_id"],
                    label=entry.get("label") or "Role",
                    emoji=entry.get("emoji"),
                    style=entry.get("style", 1),
                ))
            else:
                # Fresh creation path: (role, emoji, style_int)
                role, emoji, style_int = entry
                self.add_item(RoleButton(
                    role_id=role.id,
                    label=role.name,
                    emoji=emoji,
                    style=style_int,
                ))


# ═══════════════════════════════════════════════════════════════
#  SETUP WIZARD — Step 1: Modal
# ═══════════════════════════════════════════════════════════════

class PanelConfigModal(discord.ui.Modal, title="🎭 Role Panel Setup"):
    panel_title = discord.ui.TextInput(
        label="Panel Title",
        placeholder="e.g. Pick your Roles!",
        max_length=80,
        default="🎭 Self-Roles"
    )
    panel_description = discord.ui.TextInput(
        label="Panel Description",
        style=discord.TextStyle.paragraph,
        placeholder="Tell members what these roles are for.",
        max_length=500,
        default="Click a button below to add or remove a role!"
    )
    role_ids = discord.ui.TextInput(
        label="Role IDs (comma-separated)",
        placeholder="123456789012345678, 987654321098765432",
        style=discord.TextStyle.short,
    )
    emojis = discord.ui.TextInput(
        label="Emojis (optional, comma-separated)",
        placeholder="🎮, 🎨, 🎵  — leave blank for none",
        required=False,
    )
    panel_color = discord.ui.TextInput(
        label="Embed Color (hex, e.g. #5865F2)",
        placeholder="#5865F2",
        max_length=7,
        required=False,
        default="#5865F2"
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        config = {
            "title":       self.panel_title.value.strip(),
            "description": self.panel_description.value.strip(),
            "role_ids":    [r.strip() for r in self.role_ids.value.split(",") if r.strip()],
            "emojis":      [e.strip() for e in self.emojis.value.split(",") if e.strip()] if self.emojis.value.strip() else [],
            "color":       parse_hex_color(self.panel_color.value.strip(), 0x5865F2),
        }
        view = ChannelSelectView(self.bot, config)
        await interaction.response.send_message(
            "✅ Panel configured! Now select the channel to post it in:",
            view=view,
            ephemeral=True,
        )


# ═══════════════════════════════════════════════════════════════
#  SETUP WIZARD — Step 2: Channel Select
# ═══════════════════════════════════════════════════════════════

class ChannelSelectView(discord.ui.View):
    def __init__(self, bot: commands.Bot, config: dict):
        super().__init__(timeout=120)
        self.bot    = bot
        self.config = config

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Select a text channel…",
        channel_types=[discord.ChannelType.text],
        min_values=1,
        max_values=1,
    )
    async def channel_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        await interaction.response.defer(ephemeral=True)

        # ── FIX: resolve AppCommandChannel → real TextChannel ──
        raw_channel = select.values[0]
        channel: discord.TextChannel = raw_channel.resolve()   # type: ignore
        if channel is None:
            # Fallback: fetch from API
            channel = await interaction.guild.fetch_channel(raw_channel.id)

        guild = interaction.guild

        # Resolve roles + build entries
        role_entries     = []   # for the View: (role, emoji, style_int)
        db_entries       = []   # for DB storage
        errors           = []
        emojis           = self.config["emojis"]

        for idx, rid in enumerate(self.config["role_ids"]):
            try:
                role = guild.get_role(int(rid))
                if role is None:
                    errors.append(f"ID `{rid}` — role not found")
                    continue
                if role >= guild.me.top_role:
                    errors.append(f"`{role.name}` — above my top role, skipped")
                    continue

                emoji     = emojis[idx] if idx < len(emojis) else None
                style_int = (idx % 4) + 1   # 1-4

                role_entries.append((role, emoji, style_int))
                db_entries.append({"role_id": role.id, "label": role.name, "emoji": emoji, "style": style_int})
            except ValueError:
                errors.append(f"`{rid}` — not a valid ID")

        if not role_entries:
            await interaction.followup.send(
                embed=error_embed("No Valid Roles", "\n".join(errors) or "All role IDs were invalid."),
                ephemeral=True
            )
            return

        # Build embed + view
        embed = discord.Embed(
            title=self.config["title"],
            description=self.config["description"],
            color=self.config["color"]
        )
        embed.set_footer(text="Click a button to toggle a role!")

        view = RolePickerView(role_entries)

        # Send to chosen channel
        message = await channel.send(embed=embed, view=view)

        # Save to DB
        panel_id = await db.save_role_panel(
            guild_id    = guild.id,
            channel_id  = channel.id,
            message_id  = message.id,
            title       = self.config["title"],
            description = self.config["description"],
            color       = self.config["color"],
            created_by  = interaction.user.id,
            role_entries= db_entries,
        )

        # Register as persistent so it survives bot restarts
        self.bot.add_view(view)

        # Success feedback
        roles_text = ", ".join(f"`{r.name}`" for r, _, _ in role_entries)
        feedback   = f"✅ Role panel **#{panel_id}** sent to {channel.mention}!\n**Roles:** {roles_text}"
        if errors:
            feedback += f"\n⚠️ **Skipped:** {' | '.join(errors)}"

        await interaction.followup.send(feedback, ephemeral=True)


# ═══════════════════════════════════════════════════════════════
#  COG
# ═══════════════════════════════════════════════════════════════

class Roles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

async def setup(bot: commands.Bot):
    await bot.add_cog(Roles(bot))
