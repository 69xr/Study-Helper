# ═══════════════════════════════════════════════
#  config.py  —  Severus Bot Configuration
# ═══════════════════════════════════════════════

# ── Bot Authentication ──────────────────────────
TOKEN    = "MTMxNzIwODg4NTUyMTgxMzYxNQ.GSowBU.i2oA9j4WMWsSKlLYLj_bpxBURrTsu3DfDyvf14"
OWNER_ID = 473247429375033364
PREFIX   = "!"
STATUS   = "your server 👀"

# ── Branding ─────────────────────────────────────
BOT_NAME    = "Severus"
BOT_VERSION = "2.0"
FOOTER_TEXT = "Severus Bot"
FOOTER_ICON = ""   # URL to bot avatar (optional, auto-set at runtime)

# ── Database ─────────────────────────────────────
import os as _os
DB_PATH  = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", "bot.db")
DATA_DIR = _os.path.dirname(DB_PATH)

# ── Discord OAuth2 (Dashboard) ──────────────────
CLIENT_ID          = "1317208885521813615"
CLIENT_SECRET      = "sLi0o0b5SEZdePb3bY5GNteVL5JW6R6h"
DASHBOARD_SECRET_KEY = "change-this-to-a-random-secret-string"
DASHBOARD_HOST     = "0.0.0.0"
DASHBOARD_PORT     = 5000
OAUTH_REDIRECT_URI = "http://localhost:5000/callback"
DASHBOARD_URL      = "http://localhost:5000"

# ── Color Palette ────────────────────────────────
class Colors:
    PRIMARY  = 0x5865F2   # Discord blurple
    SUCCESS  = 0x2ecc71   # Green
    ERROR    = 0xe74c3c   # Red
    WARN     = 0xf39c12   # Orange
    INFO     = 0x3498db   # Blue
    MOD      = 0xe74c3c   # Moderation red
    MUSIC    = 0x1DB954   # Spotify green
    NEUTRAL  = 0x2C2F33   # Dark grey
    GOLD     = 0xFFD700   # Gold/premium

# ── Moderation ───────────────────────────────────
# Auto-escalation is per-guild via /warnthreshold (warn_thresholds table)
MUTE_ROLE_NAME        = "Muted"

# ── Music ────────────────────────────────────────
FFMPEG_PATH    = r"C:\Users\Administrator\Downloads\ffmpeg-8.0.1-essentials_build\bin\ffmpeg.exe"   # or full path on Windows: r"C:\ffmpeg\bin\ffmpeg.exe"
MAX_QUEUE_SIZE = 100
DEFAULT_VOLUME = 50

# ── Development ──────────────────────────────────
# Set to your test server ID for instant command sync during development.
# Leave as None (or remove) for production — global sync only.
DEV_GUILD_ID = 1104701279005069334   # e.g. 1104701279005069334
