from __future__ import annotations

import config


BRAND_SETTINGS = {
    "name": getattr(config, "BOT_NAME", "Severus"),
    "version": getattr(config, "BOT_VERSION", "2.0"),
    "tagline": "Modern Discord operations, cleaner control.",
    "dashboard_title": "Discord Control Center",
    "logo_text": "C",
    "logo_url": "",
    "hero_kicker": "Precision admin tooling for Discord communities",
    "hero_title": "Run your server with sharper visibility and faster control.",
    "hero_subtitle": (
        "Moderation, focus systems, automations, embeds, music, and server workflows "
        "managed from one cleaner control surface."
    ),
    "support_email": "support@severus.local",
    "contact_email": "contact@severus.local",
    "support_discord_url": f"https://discord.com/users/{getattr(config, 'OWNER_ID', '')}",
    "invite_url": (
        f"https://discord.com/oauth2/authorize"
        f"?client_id={getattr(config, 'CLIENT_ID', '')}"
        f"&permissions=8&scope=bot+applications.commands"
    ),
    "dashboard_url": getattr(config, "DASHBOARD_URL", "http://localhost:5000"),
    "contact_blurb": "Questions, bug reports, partnership requests, and custom setup help.",
    "support_blurb": "Operator help, install guidance, playback issues, and dashboard troubleshooting.",
    "policy_summary": (
        "This dashboard stores only the minimum operational data needed to authenticate "
        "operators, manage guild settings, and provide bot-related server controls."
    ),
    "policy_items": [
        "Discord OAuth is used only to identify you and list guilds you can manage.",
        "Server settings, moderation records, aliases, and analytics remain tied to the bot's database.",
        "No payment data is processed by this dashboard.",
        "You can clear dashboard sessions by logging out.",
    ],
    "footer_note": "Built for operators who want fast workflows instead of clutter.",
}


def get_brand() -> dict:
    brand = dict(BRAND_SETTINGS)
    brand["owner_id"] = str(getattr(config, "OWNER_ID", ""))
    brand["logo_text"] = (brand.get("logo_text") or brand["name"][:2]).upper()[:3]
    return brand
