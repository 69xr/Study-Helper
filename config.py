# ═══════════════════════════════════════════════
#  config.py  —  All bot settings in one place
# ═══════════════════════════════════════════════

# ── Bot Authentication ──────────────────────────
TOKEN    = "YOUR_BOT_TOKEN_HERE"    # <─ Bot token from Discord Developer Portal
OWNER_ID = 123456789012345678       # <─ Your Discord user ID

# ── Bot Identity ────────────────────────────────
PREFIX = "!"
STATUS = "watching over the server 👀"

# ── Database ────────────────────────────────────
# IMPORTANT: Absolute path so both the bot (run from discord_bot/)
# and the dashboard (run from discord_bot/dashboard/) always open
# the SAME database file, regardless of working directory.
import os as _os
DB_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", "bot.db")
DATA_DIR = _os.path.dirname(DB_PATH)

# ── Discord OAuth2 (for Dashboard login) ────────
# From Discord Developer Portal → OAuth2
CLIENT_ID     = "YOUR_CLIENT_ID_HERE"       # <─ Application ID
CLIENT_SECRET = "YOUR_CLIENT_SECRET_HERE"   # <─ OAuth2 Secret

# ── Dashboard ───────────────────────────────────
DASHBOARD_SECRET_KEY = "change-this-to-a-random-secret-string"
DASHBOARD_HOST       = "0.0.0.0"
DASHBOARD_PORT       = 5000
# Must match exactly what you set in Discord Developer Portal → OAuth2 → Redirects
OAUTH_REDIRECT_URI   = "http://localhost:5000/callback"
DASHBOARD_URL        = "http://localhost:5000"

# ── Colors ──────────────────────────────────────
class Colors:
    PRIMARY  = 0x5865F2
    SUCCESS  = 0x57F287
    WARNING  = 0xFEE75C
    ERROR    = 0xED4245
    INFO     = 0x5DADE2
    NEUTRAL  = 0x2F3136

# ── Moderation ──────────────────────────────────
MAX_WARNS_BEFORE_KICK = 3
