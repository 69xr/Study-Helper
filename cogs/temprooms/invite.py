import discord
from discord import app_commands
from discord.ext import commands
from utils import db
from utils.helpers import success_embed, error_embed

class TempRoomInvite(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="invite", description="Invite a user into your locked temp room.")
    @app_commands.describe(user="User to allow into your room")
    async def invite(self, interaction: discord.Interaction, user: discord.Member):
        room = await db.get_user_temp_room(interaction.guild_id, interaction.user.id)
        if not room:
            await interaction.response.send_message(
                embed=error_embed("No Room", "You don't own a temp room right now."), ephemeral=True)
            return
        vc = interaction.guild.get_channel(room["channel_id"])
        if not vc:
            await interaction.response.send_message(embed=error_embed("Room gone."), ephemeral=True)
            return
        await vc.set_permissions(user, connect=True, view_channel=True)
        await interaction.response.send_message(
            embed=success_embed("Invited", f"{user.mention} can now join your room."), ephemeral=True)
        try:
            await user.send(embed=discord.Embed(
                description=f"📨 **{interaction.user.display_name}** invited you to their voice room in **{interaction.guild.name}**!\nHead to {vc.mention} to join.",
                color=0x3d8bff))
        except: pass

async def setup(bot): await bot.add_cog(TempRoomInvite(bot))
