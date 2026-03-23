"""
cogs/community/custom_commands.py
Admins create custom text/embed commands triggered by keywords in chat.
/cc add  /cc remove  /cc list  /cc edit
Also fires from on_message — no prefix needed.
"""
import discord
from discord import app_commands
from discord.ext import commands
from utils import db
from utils.helpers import success_embed, error_embed, base_embed
import config

cc_group = app_commands.Group(name="cc", description="Manage custom commands for this server.")


class CustomCommands(commands.Cog):
    def __init__(self, bot): self.bot = bot

    # ── on_message: fire custom commands ──────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        content = message.content.strip().lower()
        if not content:
            return
        # Check first word against custom commands
        trigger = content.split()[0]
        cmd = await db.get_custom_command(message.guild.id, trigger)
        if not cmd:
            return

        await db.increment_command_uses(message.guild.id, trigger)

        if cmd["embed"]:
            color = int(cmd["embed_color"].lstrip("#"), 16) if cmd["embed_color"] else config.Colors.PRIMARY
            e = discord.Embed(
                title=cmd["embed_title"] or None,
                description=cmd["response"],
                color=color)
            e.set_footer(text=config.FOOTER_TEXT)
            try:
                await message.channel.send(embed=e)
            except discord.Forbidden:
                pass
        else:
            try:
                await message.channel.send(cmd["response"])
            except discord.Forbidden:
                pass

    # ── /cc add ────────────────────────────────────────────
    @cc_group.command(name="add", description="Create a custom command.")
    @app_commands.describe(
        trigger="Word that triggers the command (e.g. rules, info, links)",
        response="Response text (supports {user} {server} placeholders)",
        embed="Send as an embed?",
        embed_title="Embed title (if embed=true)",
        embed_color="Embed color hex (e.g. #FF5733)"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cc_add(self, interaction: discord.Interaction,
                      trigger: str, response: str,
                      embed: bool = False,
                      embed_title: str = "",
                      embed_color: str = "#5865F2"):
        trigger = trigger.lower().strip()
        if len(trigger) > 50:
            await interaction.response.send_message(
                embed=error_embed("Too Long", "Trigger must be under 50 characters."), ephemeral=True)
            return
        if " " in trigger:
            await interaction.response.send_message(
                embed=error_embed("Invalid", "Trigger must be a single word."), ephemeral=True)
            return

        await db.create_custom_command(
            interaction.guild_id, trigger, response,
            int(embed), embed_color, embed_title, interaction.user.id)

        embed_obj = success_embed("✅ Custom Command Created",
                                   f"Typing `{trigger}` in chat will now trigger this response.")
        embed_obj.add_field(name="Trigger",  value=f"`{trigger}`",           inline=True)
        embed_obj.add_field(name="As Embed", value="Yes" if embed else "No", inline=True)
        embed_obj.add_field(name="Response", value=response[:500],           inline=False)
        await interaction.response.send_message(embed=embed_obj, ephemeral=True)

    # ── /cc remove ──────────────────────────────────────────
    @cc_group.command(name="remove", description="Delete a custom command.")
    @app_commands.describe(trigger="Command trigger to remove")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cc_remove(self, interaction: discord.Interaction, trigger: str):
        removed = await db.delete_custom_command(interaction.guild_id, trigger.lower().strip())
        if not removed:
            await interaction.response.send_message(
                embed=error_embed("Not Found", f"No custom command `{trigger}`."), ephemeral=True)
            return
        await interaction.response.send_message(
            embed=success_embed("Removed", f"Custom command `{trigger}` deleted."), ephemeral=True)

    # ── /cc list ───────────────────────────────────────────
    @cc_group.command(name="list", description="List all custom commands.")
    async def cc_list(self, interaction: discord.Interaction):
        cmds = await db.get_custom_commands(interaction.guild_id)
        embed = base_embed(f"⚡ Custom Commands — {interaction.guild.name}")
        if not cmds:
            embed.description = (
                "No custom commands yet.\n"
                "Use `/cc add <trigger> <response>` to create one.")
        else:
            lines = []
            for c in cmds[:25]:
                badge = "📎" if c["embed"] else "💬"
                lines.append(f"{badge} `{c['trigger']}` — {c['uses']} uses")
            embed.description = "\n".join(lines)
            embed.set_footer(text=f"{len(cmds)} command(s) • {config.FOOTER_TEXT}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /cc info ───────────────────────────────────────────
    @cc_group.command(name="info", description="Get details about a custom command.")
    @app_commands.describe(trigger="Command trigger")
    async def cc_info(self, interaction: discord.Interaction, trigger: str):
        cmd = await db.get_custom_command(interaction.guild_id, trigger.lower().strip())
        if not cmd:
            await interaction.response.send_message(
                embed=error_embed("Not Found", f"No custom command `{trigger}`."), ephemeral=True)
            return
        creator = interaction.guild.get_member(cmd["created_by"])
        embed = base_embed(f"📋 Command: {cmd['trigger']}")
        embed.add_field(name="Response",  value=cmd["response"][:1024],              inline=False)
        embed.add_field(name="As Embed",  value="Yes" if cmd["embed"] else "No",     inline=True)
        embed.add_field(name="Uses",      value=f"`{cmd['uses']:,}`",                inline=True)
        embed.add_field(name="Created by",value=creator.mention if creator else f"ID:{cmd['created_by']}", inline=True)
        embed.add_field(name="Created",   value=cmd["created_at"][:10],              inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=error_embed("Missing Permissions",
                        "You need **Manage Server** to manage custom commands."),
                    ephemeral=True)


async def setup(bot):
    bot.tree.add_command(cc_group)
    await bot.add_cog(CustomCommands(bot))
