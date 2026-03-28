"""
FocusBeast — Pets Cog

Commands:
  /petshop  — browse and buy companions (paginated, 10 pets)
  /pets     — view your collection with navigation
  /renamepet— rename a pet (also accessible from collection)
"""

import discord
from discord.ext import commands
from discord import app_commands
import logging
from utils import db
from utils.focus_image_engine import PIXEL_PETS, RARITY_COLORS, RARITY_LABELS

log = logging.getLogger("Pets")

RARITY_ORDER = {"common": 0, "uncommon": 1, "rare": 2, "legendary": 3}
SORTED_PETS  = sorted(PIXEL_PETS.items(), key=lambda x: RARITY_ORDER[x[1]["rarity"]])


# ── Pet Shop Navigator ────────────────────────────────────────────────────────
class ShopNav(discord.ui.View):
    def __init__(self, cog: "PetsCog", user: discord.User, page: int = 0):
        super().__init__(timeout=180)
        self.cog  = cog
        self.user = user
        self.page = page
        self._update_buttons()

    def _update_buttons(self):
        sp, pd = SORTED_PETS[self.page]
        # Enable/disable buy based on rarity colour for visual feedback
        pass

    async def _check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.user.id:
            await i.response.send_message(
                "This isn't your shop session — use `/petshop` yourself.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=0)
    async def prev(self, i: discord.Interaction, _):
        if not await self._check(i):
            return
        self.page = (self.page - 1) % len(SORTED_PETS)
        await self._refresh(i)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=0)
    async def nxt(self, i: discord.Interaction, _):
        if not await self._check(i):
            return
        self.page = (self.page + 1) % len(SORTED_PETS)
        await self._refresh(i)

    @discord.ui.button(label="Buy", style=discord.ButtonStyle.success, row=0)
    async def buy(self, i: discord.Interaction, _):
        if not await self._check(i):
            return
        sp, pd = SORTED_PETS[self.page]
        await self.cog._do_buy(i, sp, pd)

    async def _refresh(self, i: discord.Interaction):
        sp, pd = SORTED_PETS[self.page]
        em, f  = await self.cog._shop_card(sp, pd, self.user)
        await i.response.edit_message(embed=em, attachments=[f], view=self)


# ── Pet Collection Navigator ──────────────────────────────────────────────────
class CollectionNav(discord.ui.View):
    def __init__(self, cog: "PetsCog", user: discord.User, pets: list, page: int = 0):
        super().__init__(timeout=180)
        self.cog  = cog
        self.user = user
        self.pets = list(pets)
        self.page = page

    async def _check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.user.id:
            await i.response.send_message(
                "This isn't your collection.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=0)
    async def prev(self, i: discord.Interaction, _):
        if not await self._check(i):
            return
        self.page = (self.page - 1) % len(self.pets)
        await self._refresh(i)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=0)
    async def nxt(self, i: discord.Interaction, _):
        if not await self._check(i):
            return
        self.page = (self.page + 1) % len(self.pets)
        await self._refresh(i)

    @discord.ui.button(label="Set Active", style=discord.ButtonStyle.primary, row=0)
    async def activate(self, i: discord.Interaction, _):
        if not await self._check(i):
            return
        pet = self.pets[self.page]
        if pet["active"]:
            return await i.response.send_message(
                f"**{pet['name']}** is already your active companion!",
                ephemeral=True,
            )
        await db.set_active_focus_pet(self.user.id, pet["pet_id"])
        # Reload pets to reflect active flag
        self.pets = list(await db.get_focus_pets(self.user.id))
        self.page = next(
            (idx for idx, p in enumerate(self.pets) if p["active"]), 0
        )
        await self._refresh(i)
        await i.followup.send(
            f"**{pet['name']}** is now your active companion!",
            ephemeral=True,
        )

    @discord.ui.button(label="Rename", style=discord.ButtonStyle.secondary, row=1)
    async def rename(self, i: discord.Interaction, _):
        if not await self._check(i):
            return
        pet = self.pets[self.page]
        await i.response.send_modal(
            RenameModal(self.cog, pet["pet_id"], self.user.id, self)
        )

    async def _refresh(self, i: discord.Interaction):
        pet   = self.pets[self.page]
        em, f = await self.cog._pet_card(pet, self.page, len(self.pets))
        await i.response.edit_message(embed=em, attachments=[f], view=self)


# ── Rename Modal ──────────────────────────────────────────────────────────────
class RenameModal(discord.ui.Modal, title="Rename Companion"):
    new_name = discord.ui.TextInput(
        label="New Name",
        placeholder="Enter a name (max 32 characters)",
        min_length=1,
        max_length=32,
    )

    def __init__(self, cog: "PetsCog", pet_id: int,
                 uid: int, nav: CollectionNav = None):
        super().__init__()
        self.cog    = cog
        self.pet_id = pet_id
        self.uid    = uid
        self.nav    = nav   # optional — to refresh the collection view after rename

    async def on_submit(self, i: discord.Interaction):
        name = self.new_name.value.strip()

        # Validate: no mention strings or weird content
        if "@" in name or "#" in name:
            return await i.response.send_message(
                "Pet name cannot contain @ or # symbols.", ephemeral=True
            )

        await db.rename_focus_pet(self.pet_id, self.uid, name)
        pet = await db.get_focus_pet(self.pet_id)

        if self.nav:
            # Reload pets and refresh the collection view
            self.nav.pets = list(
                await db.get_focus_pets(self.uid)
            )
            em, f = await self.cog._pet_card(pet, self.nav.page, len(self.nav.pets))
            em.description = f"Renamed to **{name}**!\n\n" + (em.description or "")
            await i.response.edit_message(embed=em, attachments=[f], view=self.nav)
        else:
            em, f = await self.cog._pet_card(pet)
            await i.response.send_message(
                embed=em, file=f, ephemeral=True
            )


# ── Pets Cog ──────────────────────────────────────────────────────────────────
class PetsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── /petshop ──────────────────────────────────────────────────────────────
    @app_commands.command(name="petshop", description="Browse and adopt focus companions")
    async def petshop(self, i: discord.Interaction):
        sp, pd = SORTED_PETS[0]
        em, f  = await self._shop_card(sp, pd, i.user)
        await i.response.send_message(
            embed=em, file=f, view=ShopNav(self, i.user)
        )

    # ── /pets ─────────────────────────────────────────────────────────────────
    @app_commands.command(
        name="pets", description="View your companion collection and active pet"
    )
    @app_commands.describe(user="View another member's collection (read-only)")
    async def pets(self, i: discord.Interaction,
                   user: discord.Member = None):
        target    = user or i.user
        read_only = (user is not None and user.id != i.user.id)
        owned     = await db.get_focus_pets(target.id)
        if not owned:
            msg = (
                "No companions yet — use `/petshop` to adopt one!"
                if not read_only
                else f"{target.display_name} hasn't adopted any companions yet."
            )
            return await i.response.send_message(msg, ephemeral=True)

        em, f = await self._pet_card(owned[0], 0, len(owned))
        view  = CollectionNav(self, target, owned) if not read_only else None
        await i.response.send_message(embed=em, file=f, view=view)

    # ── /renamepet ────────────────────────────────────────────────────────────
    @app_commands.command(name="renamepet", description="Rename one of your companions")
    @app_commands.describe(pet_id="Pet ID shown on the card")
    async def renamepet(self, i: discord.Interaction, pet_id: int):
        pet = await db.get_focus_pet(pet_id)
        if not pet or pet["user_id"] != i.user.id:
            return await i.response.send_message(
                "That pet doesn't exist or doesn't belong to you.", ephemeral=True
            )
        await i.response.send_modal(RenameModal(self, pet_id, i.user.id))

    # ── Internal: build shop card ─────────────────────────────────────────────
    async def _shop_card(self, species: str, pd: dict, user: discord.User):
        u     = await db.get_focus_user(user.id)
        coins = u["coins"] if u else 0
        pets  = await db.get_focus_pets(user.id)
        owned = any(p["species"] == species for p in pets)
        buf   = self.bot.focus_image_engine.render_pet_shop_card(species)
        file  = discord.File(buf, filename="pet_shop.png")
        idx   = next(j for j, (s, _) in enumerate(SORTED_PETS) if s == species)
        rc    = RARITY_COLORS[pd["rarity"]]
        embed = discord.Embed(
            title=(
                f"{'✅ Owned' if owned else '🛒 For Sale'}  —  "
                f"{species.replace('_', ' ').title()}"
            ),
            description=(
                f"*{pd['desc']}*\n\n"
                f"**Rarity:** {RARITY_LABELS[pd['rarity']]}\n"
                f"**Price:** {pd['price']:,} coins\n"
                f"**Your balance:** {coins:,} coins\n\n"
                f"{'✅ Already in your collection!' if owned else 'Press **Buy** to adopt.'}"
            ),
            color=discord.Color.from_rgb(*rc),
        )
        embed.set_image(url="attachment://pet_shop.png")
        embed.set_footer(
            text=f"Pet {idx + 1} of {len(SORTED_PETS)}  ·  ◀ ▶ to browse"
        )
        return embed, file

    # ── Internal: build pet card ──────────────────────────────────────────────
    async def _pet_card(self, pet, page: int = 0, total: int = 1):
        rc  = RARITY_COLORS[pet["rarity"]]
        buf = self.bot.focus_image_engine.render_pet_card(
            pet["species"], pet["name"],
            pet["level"], pet["xp"], pet["happiness"],
            bool(pet["active"]),
        )
        file  = discord.File(buf, filename="pet_card.png")
        embed = discord.Embed(
            title=(
                f"{'⭐ Active — ' if pet['active'] else ''}"
                f"{pet['name']}"
            ),
            description=(
                f"**Species:** {pet['species'].replace('_', ' ').title()}\n"
                f"**Rarity:** {RARITY_LABELS[pet['rarity']]}\n"
                f"**Level:** {pet['level']}  "
                f"({pet['xp']} / {pet['level'] * 100} XP)\n"
                f"**Happiness:** {pet['happiness']}%\n"
                f"**Pet ID:** `{pet['pet_id']}`\n\n"
                f"{'Currently active — shown on your timer.' if pet['active'] else 'Press **Set Active** to equip.'}"
            ),
            color=discord.Color.from_rgb(*rc),
        )
        embed.set_image(url="attachment://pet_card.png")
        embed.set_footer(
            text=f"Pet {page + 1} of {total}  ·  "
                 f"Use Rename button or /renamepet {pet['pet_id']}"
        )
        return embed, file

    # ── Internal: purchase flow ────────────────────────────────────────────────
    async def _do_buy(self, i: discord.Interaction, species: str, pd: dict):
        # Already owns it?
        pets = await db.get_focus_pets(i.user.id)
        if any(p["species"] == species for p in pets):
            return await i.response.send_message(
                f"You already own a **{species.replace('_', ' ').title()}**!",
                ephemeral=True,
            )

        # Sufficient coins?
        if not await db.spend_focus_coins(i.user.id, pd["price"]):
            u = await db.get_focus_user(i.user.id)
            shortage = pd["price"] - u["coins"]
            return await i.response.send_message(
                f"Not enough coins.\n"
                f"You have **{u['coins']:,}** — need **{pd['price']:,}** "
                f"(short by **{shortage:,}**).",
                ephemeral=True,
            )

        name   = species.replace("_", " ").title()
        pet_id = await db.add_focus_pet(i.user.id, species, name, pd["rarity"])
        await db.add_focus_audit(
            i.user.id, i.guild_id, 0, -pd["price"], f"pet_buy:{species}"
        )

        rc   = RARITY_COLORS[pd["rarity"]]
        buf  = self.bot.focus_image_engine.render_pet_card(species, name, 1, 0, 100, False)
        file = discord.File(buf, filename="new_pet.png")
        embed = discord.Embed(
            title="New Companion Adopted! 🎉",
            description=(
                f"**{name}** ({RARITY_LABELS[pd['rarity']]}) joined your team!\n\n"
                f"Use the **Rename** button in `/pets` to give them a personal name.\n"
                f"Use `/pets` → **Set Active** to display them on your timer.\n\n"
                f"*Pet ID: `{pet_id}`*"
            ),
            color=discord.Color.from_rgb(*rc),
        )
        embed.set_image(url="attachment://new_pet.png")
        await i.response.send_message(embed=embed, file=file)


async def setup(bot):
    await bot.add_cog(PetsCog(bot))
