"""
cogs/tickets.py
Commands : /ticket open  /ticket close  /ticket claim  /ticket add  /ticket remove
           /ticket transcript  /ticket panel  /ticketsetup
Events   : on_message (log ticket messages for transcript)
"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
import asyncio
from utils import db
from utils.helpers import success_embed, error_embed, warning_embed, send_log


# ══════════════════════════════════════════════════════
#  PERSISTENT OPEN-TICKET BUTTON
# ══════════════════════════════════════════════════════

class TicketOpenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open a Ticket", emoji="🎫",
                       style=discord.ButtonStyle.primary,
                       custom_id="ticket_open_btn")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        settings = await db.get_ticket_settings(interaction.guild_id)
        open_tickets = await db.get_user_open_tickets(interaction.guild_id, interaction.user.id)

        if len(open_tickets) >= settings["max_open"]:
            ch = interaction.guild.get_channel(open_tickets[0]["channel_id"])
            await interaction.followup.send(
                embed=error_embed("Ticket Exists",
                    f"You already have an open ticket: {ch.mention if ch else '(deleted)'}"),
                ephemeral=True
            )
            return

        # Create the ticket channel
        category = interaction.guild.get_channel(settings["category_id"]) if settings["category_id"] else None
        ticket_num = (await db.get_ticket_settings(interaction.guild_id))["counter"] + 1

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user:               discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
            interaction.guild.me:           discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if settings["support_role"]:
            role = interaction.guild.get_role(settings["support_role"])
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        channel = await interaction.guild.create_text_channel(
            name=f"ticket-{ticket_num:04d}",
            category=category,
            overwrites=overwrites,
            topic=f"Ticket for {interaction.user} | ID: {interaction.user.id}"
        )

        ticket_id = await db.create_ticket(
            interaction.guild_id, channel.id, interaction.user.id, "Support Ticket"
        )

        # Send welcome embed in ticket channel
        embed = discord.Embed(
            title=f"🎫  Ticket #{ticket_num:04d}",
            description=settings["ticket_msg"],
            color=0x3d8bff
        )
        embed.add_field(name="Opened by", value=interaction.user.mention, inline=True)
        embed.add_field(name="Ticket ID", value=f"`#{ticket_id}`", inline=True)
        embed.set_footer(text="Use the buttons below to manage this ticket.")

        view = TicketControlView(ticket_id)
        await channel.send(content=interaction.user.mention, embed=embed, view=view)

        await interaction.followup.send(
            embed=success_embed("Ticket Opened", f"Your ticket is ready: {channel.mention}"),
            ephemeral=True
        )

        # Log
        log_ch = settings.get("log_channel")
        if log_ch:
            log_embed = discord.Embed(
                title="🎫 Ticket Opened", color=0x3d8bff,
                timestamp=datetime.now(timezone.utc)
            )
            log_embed.add_field(name="User",    value=f"{interaction.user.mention} (`{interaction.user}`)")
            log_embed.add_field(name="Channel", value=channel.mention)
            log_embed.add_field(name="ID",      value=f"`#{ticket_id}`")
            await send_log(interaction.guild, log_ch, log_embed)


# ══════════════════════════════════════════════════════
#  TICKET CONTROL BUTTONS (inside ticket channel)
# ══════════════════════════════════════════════════════

class TicketControlView(discord.ui.View):
    def __init__(self, ticket_id: int = None):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id


    @discord.ui.button(label="Close", emoji="🔒",
                       style=discord.ButtonStyle.danger,
                       custom_id="ticket_close_btn")
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = await db.get_ticket_by_channel(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message(embed=error_embed("Not a ticket channel."), ephemeral=True)
            return
        if ticket["status"] != "open":
            await interaction.response.send_message(embed=error_embed("Already closed."), ephemeral=True)
            return

        await interaction.response.send_message(
            embed=warning_embed("Close Ticket", "Are you sure you want to close this ticket?"),
            view=ConfirmCloseView(ticket["id"]),
            ephemeral=True
        )

    @discord.ui.button(label="Claim", emoji="🙋",
                       style=discord.ButtonStyle.success,
                       custom_id="ticket_claim_btn")
    async def claim_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = await db.get_ticket_by_channel(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message(embed=error_embed("Not a ticket."), ephemeral=True)
            return

        settings = await db.get_ticket_settings(interaction.guild_id)
        if settings["support_role"]:
            role = interaction.guild.get_role(settings["support_role"])
            if role and role not in interaction.user.roles:
                await interaction.response.send_message(
                    embed=error_embed("No Permission", "Only support staff can claim tickets."), ephemeral=True
                )
                return

        if ticket["claimed_by"]:
            claimer = interaction.guild.get_member(ticket["claimed_by"])
            await interaction.response.send_message(
                embed=error_embed("Already Claimed", f"Claimed by {claimer.mention if claimer else 'someone'}."),
                ephemeral=True
            )
            return

        await db.update_ticket(ticket["id"], claimed_by=interaction.user.id)
        embed = discord.Embed(
            description=f"✋  {interaction.user.mention} has claimed this ticket.",
            color=0x3dffaa
        )
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="Transcript", emoji="📄",
                       style=discord.ButtonStyle.secondary,
                       custom_id="ticket_transcript_btn")
    async def transcript_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = await db.get_ticket_by_channel(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message(embed=error_embed("Not a ticket."), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await _send_transcript(interaction, ticket)


class ConfirmCloseView(discord.ui.View):
    def __init__(self, ticket_id: int):
        super().__init__(timeout=60)
        self.ticket_id = ticket_id

    @discord.ui.button(label="Yes, Close", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = await db.get_ticket_by_channel(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message("Not a ticket.", ephemeral=True)
            return

        await db.update_ticket(ticket["id"], status="closed",
                                closed_at=datetime.now(timezone.utc).isoformat())

        settings = await db.get_ticket_settings(interaction.guild_id)
        embed = discord.Embed(
            title="🔒  Ticket Closed",
            description=f"Closed by {interaction.user.mention}",
            color=0xff3d5a,
            timestamp=datetime.now(timezone.utc)
        )
        await interaction.channel.send(embed=embed)
        await interaction.response.send_message(
            embed=success_embed("Closed", "Ticket will be deleted in 5 seconds."), ephemeral=True
        )

        # Log + transcript
        if settings.get("log_channel"):
            await _send_transcript_to_log(interaction.guild, settings["log_channel"], ticket)

        await asyncio.sleep(5)
        try: await interaction.channel.delete(reason="Ticket closed")
        except: pass
        await db.update_ticket(ticket["id"], status="deleted")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Cancelled.", view=None, embed=None)

    async def on_timeout(self):
        """Called when the 60s confirmation window expires."""
        try:
            # Disable all buttons to show the view has expired
            for item in self.children:
                item.disabled = True
        except Exception:
            pass


# ══════════════════════════════════════════════════════
#  TRANSCRIPT HELPERS
# ══════════════════════════════════════════════════════

async def _build_transcript(ticket: dict, messages: list[dict]) -> str:
    lines = [
        f"TICKET TRANSCRIPT  |  #{ticket['ticket_num']:04d}",
        f"Opened by: {ticket['user_id']}",
        f"Status:    {ticket['status']}",
        f"Opened:    {ticket['opened_at']}",
        f"Closed:    {ticket.get('closed_at') or 'still open'}",
        "─" * 60,
        ""
    ]
    for m in messages:
        lines.append(f"[{m['sent_at'][:16]}] {m['author_tag']}: {m['content']}")
    return "\n".join(lines)

async def _send_transcript(interaction: discord.Interaction, ticket: dict):
    messages = await db.get_ticket_messages(ticket["id"])
    text = await _build_transcript(ticket, messages)
    file = discord.File(
        fp=__import__("io").BytesIO(text.encode()),
        filename=f"ticket-{ticket['ticket_num']:04d}-transcript.txt"
    )
    try:
        opener = interaction.guild.get_member(ticket["user_id"])
        if opener:
            await opener.send(
                embed=discord.Embed(title="📄 Ticket Transcript", color=0x3d8bff,
                    description=f"Transcript for ticket #{ticket['ticket_num']:04d}"),
                file=file
            )
    except: pass
    await interaction.followup.send("📄 Transcript sent to the ticket opener's DMs.", ephemeral=True)

async def _send_transcript_to_log(guild: discord.Guild, log_channel_id: int, ticket: dict):
    messages = await db.get_ticket_messages(ticket["id"])
    text = await _build_transcript(ticket, messages)
    ch = guild.get_channel(log_channel_id)
    if not ch: return
    file = discord.File(
        fp=__import__("io").BytesIO(text.encode()),
        filename=f"ticket-{ticket['ticket_num']:04d}-transcript.txt"
    )
    embed = discord.Embed(title="📄 Ticket Closed", color=0xff3d5a)
    embed.add_field(name="Ticket #", value=f"`{ticket['ticket_num']:04d}`", inline=True)
    embed.add_field(name="User",     value=f"`{ticket['user_id']}`",        inline=True)
    embed.add_field(name="Messages", value=f"`{len(messages)}`",            inline=True)
    try: await ch.send(embed=embed, file=file)
    except: pass


# ══════════════════════════════════════════════════════
#  COG
# ══════════════════════════════════════════════════════

ticket_group = app_commands.Group(name="ticket", description="Ticket management commands.")


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Register persistent views
        bot.add_view(TicketOpenView())
        bot.add_view(TicketControlView())

    # ── Log messages in ticket channels ──────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild: return
        ticket = await db.get_ticket_by_channel(message.channel.id)
        if not ticket or ticket["status"] != "open": return
        await db.save_ticket_message(
            ticket["id"], message.author.id,
            str(message.author), message.content[:2000]
        )

    # ── /ticket open ─────────────────────────────────────────
    @ticket_group.command(name="open", description="Open a support ticket.")
    @app_commands.describe(subject="Brief description of your issue.")
    async def ticket_open(self, interaction: discord.Interaction, subject: str = "Support Ticket"):
        await interaction.response.defer(ephemeral=True)
        settings = await db.get_ticket_settings(interaction.guild_id)
        open_tickets = await db.get_user_open_tickets(interaction.guild_id, interaction.user.id)
        if len(open_tickets) >= settings["max_open"]:
            ch = interaction.guild.get_channel(open_tickets[0]["channel_id"])
            await interaction.followup.send(
                embed=error_embed("Already Open", f"You have an open ticket: {ch.mention if ch else '(deleted)'}"),
                ephemeral=True
            )
            return

        category = interaction.guild.get_channel(settings["category_id"]) if settings["category_id"] else None
        ticket_num = settings["counter"] + 1

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user:               discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
            interaction.guild.me:           discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if settings["support_role"]:
            role = interaction.guild.get_role(settings["support_role"])
            if role: overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        channel = await interaction.guild.create_text_channel(
            name=f"ticket-{ticket_num:04d}", category=category,
            overwrites=overwrites,
            topic=f"Ticket for {interaction.user} | {subject}"
        )
        ticket_id = await db.create_ticket(interaction.guild_id, channel.id, interaction.user.id, subject)

        embed = discord.Embed(title=f"🎫  Ticket #{ticket_num:04d}", description=settings["ticket_msg"], color=0x3d8bff)
        embed.add_field(name="Subject",    value=subject,                  inline=False)
        embed.add_field(name="Opened by",  value=interaction.user.mention, inline=True)
        embed.set_footer(text="Use the buttons below to manage this ticket.")
        await channel.send(content=interaction.user.mention, embed=embed, view=TicketControlView(ticket_id))
        await interaction.followup.send(embed=success_embed("Ticket Created", f"Opened: {channel.mention}"), ephemeral=True)

    # ── /ticket close ────────────────────────────────────────
    @ticket_group.command(name="close", description="Close the current ticket.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def ticket_close(self, interaction: discord.Interaction):
        ticket = await db.get_ticket_by_channel(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message(embed=error_embed("Not a ticket channel."), ephemeral=True)
            return
        await interaction.response.send_message(
            embed=warning_embed("Close Ticket", "Confirm you want to close this ticket?"),
            view=ConfirmCloseView(ticket["id"]), ephemeral=True
        )

    # ── /ticket claim ────────────────────────────────────────
    @ticket_group.command(name="claim", description="Claim this ticket as your own.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def ticket_claim(self, interaction: discord.Interaction):
        ticket = await db.get_ticket_by_channel(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message(embed=error_embed("Not a ticket channel."), ephemeral=True)
            return
        if ticket["claimed_by"]:
            m = interaction.guild.get_member(ticket["claimed_by"])
            await interaction.response.send_message(
                embed=error_embed("Already Claimed", f"By {m.mention if m else ticket['claimed_by']}."), ephemeral=True
            )
            return
        await db.update_ticket(ticket["id"], claimed_by=interaction.user.id)
        await interaction.response.send_message(
            embed=success_embed("Claimed", f"{interaction.user.mention} is now handling this ticket.")
        )

    # ── /ticket add ──────────────────────────────────────────
    @ticket_group.command(name="add", description="Add a user to this ticket.")
    @app_commands.describe(user="User to add")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def ticket_add(self, interaction: discord.Interaction, user: discord.Member):
        ticket = await db.get_ticket_by_channel(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message(embed=error_embed("Not a ticket channel."), ephemeral=True)
            return
        await interaction.channel.set_permissions(user, view_channel=True, send_messages=True)
        await interaction.response.send_message(
            embed=success_embed("Added", f"{user.mention} has been added to the ticket.")
        )

    # ── /ticket remove ───────────────────────────────────────
    @ticket_group.command(name="remove", description="Remove a user from this ticket.")
    @app_commands.describe(user="User to remove")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def ticket_remove(self, interaction: discord.Interaction, user: discord.Member):
        ticket = await db.get_ticket_by_channel(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message(embed=error_embed("Not a ticket channel."), ephemeral=True)
            return
        await interaction.channel.set_permissions(user, overwrite=None)
        await interaction.response.send_message(
            embed=success_embed("Removed", f"{user.mention} has been removed from the ticket.")
        )

    # ── /ticket panel ────────────────────────────────────────
    @ticket_group.command(name="panel", description="Send the ticket open panel to this channel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ticket_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎫  Support Tickets",
            description="Need help? Click the button below to open a ticket.\nOur support team will assist you shortly.",
            color=0x3d8bff
        )
        embed.set_footer(text=interaction.guild.name)
        await interaction.channel.send(embed=embed, view=TicketOpenView())
        await interaction.response.send_message(
            embed=success_embed("Panel Sent", "The ticket panel has been posted."), ephemeral=True
        )

    # ── /ticketsetup ─────────────────────────────────────────
    @app_commands.command(name="ticketsetup", description="Configure the ticket system.")
    @app_commands.describe(
        category="Category for new ticket channels",
        log_channel="Channel for ticket logs",
        support_role="Role that can see all tickets",
        max_open="Max open tickets per user (default 1)"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ticketsetup(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel = None,
        log_channel: discord.TextChannel  = None,
        support_role: discord.Role        = None,
        max_open: app_commands.Range[int, 1, 5] = 1
    ):
        if category:    await db.set_ticket_setting(interaction.guild_id, "category_id",  category.id)
        if log_channel: await db.set_ticket_setting(interaction.guild_id, "log_channel",  log_channel.id)
        if support_role:await db.set_ticket_setting(interaction.guild_id, "support_role", support_role.id)
        await db.set_ticket_setting(interaction.guild_id, "max_open", max_open)

        embed = success_embed("Ticket System Configured")
        embed.add_field(name="Category",     value=category.mention    if category     else "Not set", inline=True)
        embed.add_field(name="Log Channel",  value=log_channel.mention if log_channel  else "Not set", inline=True)
        embed.add_field(name="Support Role", value=support_role.mention if support_role else "Not set", inline=True)
        embed.add_field(name="Max Open",     value=str(max_open),                                       inline=True)
        embed.description = "Use `/ticket panel` to post the open-ticket button in a channel."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── error handler ─────────────────────────────────────────
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=error_embed("Missing Permissions", "You don't have permission to use this command."),
                    ephemeral=True
                )


async def setup(bot: commands.Bot):
    cog = Tickets(bot)
    bot.tree.add_command(ticket_group)
    await bot.add_cog(cog)
