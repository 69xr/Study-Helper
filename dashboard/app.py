"""
dashboard/app.py  —  Flask dashboard with Discord OAuth2 + SocketIO
Run separately from the bot:  python dashboard/app.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import (
    Flask, render_template, redirect, url_for,
    session, request, jsonify, flash
)
from flask_socketio import SocketIO, emit
import requests as req
import asyncio, aiosqlite, json, threading, time
from functools import wraps
from datetime import datetime, timezone
import config
from utils.product_catalog import ALIAS_COMMANDS
from dashboard.branding import get_brand

import hashlib, pickle, pathlib

app = Flask(__name__)
app.secret_key = config.DASHBOARD_SECRET_KEY
app.jinja_env.globals["brand"] = get_brand()

# ── Flask-SocketIO ─────────────────────────────────────────────
#  async_mode='threading' works with Flask dev server + eventlet/gevent.
#  For production swap to async_mode='eventlet' after pip install eventlet.
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading", logger=False, engineio_logger=False)

# ── IPC ───────────────────────────────────────────────────────
try:
    from utils.ipc import (dash_read_events, dash_send_command,
                           dash_get_recent_logs, dash_poll_ack,
                           read_module_state)
    _IPC_AVAILABLE = True
except Exception as _e:
    print(f"  ⚠  IPC not available: {_e}")
    _IPC_AVAILABLE = False
    def dash_read_events(since=0): return [], since
    def dash_send_command(action, params=None, cmd_id=None): return ""
    def dash_get_recent_logs(n=100): return []
    def dash_poll_ack(cmd_id, max_wait=8): return {"ok": False, "msg": "IPC not available"}
    def read_module_state(): return {}

# ─────────────────────────────────────────────────────────────
#  DB AUTO-INIT
#  Ensures all tables exist whether the dashboard is started
#  standalone or alongside the bot. Runs once per process.
# ─────────────────────────────────────────────────────────────
_db_initialized = False

def _ensure_db():
    global _db_initialized
    if _db_initialized:
        return
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from utils import db as _db_mod
        os.makedirs(config.DATA_DIR, exist_ok=True)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_db_mod.init_db())
            loop.run_until_complete(_db_mod.init_new_tables())
            loop.run_until_complete(_db_mod.cleanup_removed_features())
        finally:
            loop.close()
        _db_initialized = True
    except Exception as e:
        print(f"  ⚠️  DB init warning: {e}")

@app.before_request
def before_request():
    _ensure_db()


@app.context_processor
def inject_brand():
    return {"brand": get_brand()}

# ─────────────────────────────────────────────────────────────
#  SERVER-SIDE SESSION CACHE
#  Stores large data (guilds list, access token) on disk keyed
#  by a random session ID — keeps the cookie tiny (<200 bytes).
# ─────────────────────────────────────────────────────────────
_CACHE_DIR = pathlib.Path(config.DATA_DIR) / "session_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

def _cache_path(sid: str) -> pathlib.Path:
    safe = hashlib.sha256(sid.encode()).hexdigest()
    return _CACHE_DIR / f"{safe}.pkl"

def cache_set(sid: str, data: dict) -> None:
    with open(_cache_path(sid), "wb") as f:
        pickle.dump(data, f)

def cache_get(sid: str) -> dict | None:
    p = _cache_path(sid)
    if not p.exists():
        return None
    try:
        with open(p, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None

def cache_delete(sid: str) -> None:
    p = _cache_path(sid)
    if p.exists():
        p.unlink()

def _get_guilds() -> list:
    """Load guilds from server-side cache using session id."""
    sid = session.get("sid")
    if not sid:
        return []
    data = cache_get(sid)
    return data.get("guilds", []) if data else []

def _get_token() -> str | None:
    sid = session.get("sid")
    if not sid:
        return None
    data = cache_get(sid)
    return data.get("token") if data else None

DISCORD_API = "https://discord.com/api/v10"
OAUTH_URL = (
    f"https://discord.com/oauth2/authorize"
    f"?client_id={config.CLIENT_ID}"
    f"&redirect_uri={req.utils.quote(config.OAUTH_REDIRECT_URI)}"
    f"&response_type=code&scope=identify+guilds"
)

# ─────────────────────────────────────────────────────────────
#  CORE HELPERS
# ─────────────────────────────────────────────────────────────

def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

def discord_req(endpoint, token):
    r = req.get(f"{DISCORD_API}{endpoint}",
                headers={"Authorization": f"Bearer {token}"}, timeout=8)
    return r.json() if r.ok else None

def bot_req(endpoint):
    r = req.get(f"{DISCORD_API}{endpoint}",
                headers={"Authorization": f"Bot {config.TOKEN}"}, timeout=8)
    return r.json() if r.ok else None

# ─────────────────────────────────────────────────────────────
#  DB HELPERS
# ─────────────────────────────────────────────────────────────

async def db_fetch(q, p=()):
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(q, p) as c:
            return [dict(r) for r in await c.fetchall()]

async def db_fetchone(q, p=()):
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(q, p) as c:
            r = await c.fetchone()
            return dict(r) if r else None

async def db_execute(q, p=()):
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(q, p)
        await db.commit()

# ─────────────────────────────────────────────────────────────
#  DECORATORS
# ─────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*a, **kw)
    return dec

def guild_access_required(f):
    @wraps(f)
    def dec(guild_id, *a, **kw):
        g = next((x for x in _get_guilds()
                  if str(x["id"]) == str(guild_id)), None)
        if not g:
            flash("Server not found or no access.", "error")
            return redirect(url_for("select_server"))
        perms = int(g.get("permissions", 0))
        if not (perms & 0x20 or perms & 0x8):
            flash("You need Manage Server permission.", "error")
            return redirect(url_for("select_server"))
        return f(guild_id, *a, **kw)
    return dec

def _guild(gid):
    return next((g for g in _get_guilds()
                 if str(g["id"]) == str(gid)), {})

# ─────────────────────────────────────────────────────────────
#  AUTH
# ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect(url_for("select_server")) if "user" in session \
           else render_template("landing.html")


@app.route("/support")
def support_page():
    return render_template("support.html")


@app.route("/contact")
def contact_page():
    return render_template("contact.html")


@app.route("/policy")
def policy_page():
    return render_template("policy.html")

@app.route("/login")
def login():
    return redirect(OAUTH_URL)

@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        flash("OAuth failed.", "error")
        return redirect(url_for("index"))
    r = req.post(f"{DISCORD_API}/oauth2/token", data={
        "client_id": config.CLIENT_ID,
        "client_secret": config.CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.OAUTH_REDIRECT_URI,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=8)
    if not r.ok:
        flash("Token exchange failed.", "error")
        return redirect(url_for("index"))
    tok    = r.json()["access_token"]
    user   = discord_req("/users/@me", tok)
    guilds = discord_req("/users/@me/guilds", tok)
    if not user:
        flash("Could not fetch user.", "error")
        return redirect(url_for("index"))
    # Slim the user object — only keep what the templates use
    slim_user = {
        "id":            user["id"],
        "username":      user.get("username", ""),
        "discriminator": user.get("discriminator", "0"),
        "avatar":        user.get("avatar"),
    }
    # Slim each guild — only id, name, icon, permissions
    slim_guilds = [
        {
            "id":          g["id"],
            "name":        g.get("name", ""),
            "icon":        g.get("icon"),
            "permissions": g.get("permissions", "0"),
        }
        for g in (guilds or [])
    ]

    # Generate a unique session ID and store heavy data server-side
    import secrets
    sid = secrets.token_hex(32)
    cache_set(sid, {"token": tok, "guilds": slim_guilds})

    # Only tiny data goes in the cookie
    session.clear()
    session["user"] = slim_user
    session["sid"]  = sid
    session.permanent = False
    return redirect(url_for("select_server"))

@app.route("/logout")
def logout():
    sid = session.get("sid")
    if sid:
        cache_delete(sid)
    session.clear()
    return redirect(url_for("index"))

# ─────────────────────────────────────────────────────────────
#  SERVER SELECT
# ─────────────────────────────────────────────────────────────

@app.route("/servers")
@login_required
def select_server():
    # Primary: ask Discord which guilds the bot is actually in.
    # This is authoritative — works even if guild_settings has no row yet.
    bot_guilds_raw = bot_req("/users/@me/guilds?limit=200") or []
    bot_ids = {str(g["id"]) for g in bot_guilds_raw if isinstance(g, dict)}

    # Fallback: also include any guild_ids already in our DB
    # (covers edge case where bot API fails but bot is running)
    try:
        db_ids = {str(g["guild_id"]) for g in
                  run_async(db_fetch("SELECT guild_id FROM guild_settings"))}
        bot_ids |= db_ids
    except Exception:
        pass  # table may not exist yet on a brand-new install

    manageable = []
    for g in _get_guilds():
        p = int(g.get("permissions", 0))
        if p & 0x20 or p & 0x8:
            g["bot_added"] = str(g["id"]) in bot_ids
            manageable.append(g)
    manageable.sort(key=lambda g: (not g["bot_added"], g.get("name", "")))
    return render_template("servers.html", guilds=manageable, user=session["user"])

# ─────────────────────────────────────────────────────────────
#  DASHBOARD OVERVIEW
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>")
@login_required
@guild_access_required
def dashboard(guild_id):
    # Ensure guild has a settings row — creates one with defaults if missing
    run_async(db_execute(
        "INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (int(guild_id),)
    ))
    settings = run_async(db_fetchone("SELECT * FROM guild_settings WHERE guild_id=?", (guild_id,))) or {}
    warn_count   = (run_async(db_fetchone("SELECT COUNT(*) as c FROM warnings WHERE guild_id=?",    (guild_id,))) or {}).get("c", 0)
    panel_count  = (run_async(db_fetchone("SELECT COUNT(*) as c FROM role_panels WHERE guild_id=?", (guild_id,))) or {}).get("c", 0)
    cmd_count    = (run_async(db_fetchone("SELECT COUNT(*) as c FROM command_stats WHERE guild_id=?",(guild_id,))) or {}).get("c", 0)
    bl_count     = (run_async(db_fetchone("SELECT COUNT(*) as c FROM blacklist"))                   or {}).get("c", 0)
    recent_warns = run_async(db_fetch("SELECT * FROM warnings WHERE guild_id=? ORDER BY created_at DESC LIMIT 5", (guild_id,)))
    top_cmds     = run_async(db_fetch("SELECT command, COUNT(*) as uses FROM command_stats WHERE guild_id=? GROUP BY command ORDER BY uses DESC LIMIT 5", (guild_id,)))
    recent_audit = run_async(db_fetch("SELECT * FROM audit_log WHERE guild_id=? ORDER BY created_at DESC LIMIT 6", (guild_id,)))
    audit_count  = (run_async(db_fetchone("SELECT COUNT(*) as c FROM audit_log WHERE guild_id=?", (guild_id,))) or {}).get("c", 0)
    sparkline    = run_async(db_fetch("SELECT DATE(used_at) as day, COUNT(*) as uses FROM command_stats WHERE guild_id=? AND used_at >= DATE('now','-7 days') GROUP BY day ORDER BY day", (guild_id,)))
    return render_template("dashboard.html",
        guild=_guild(guild_id), guild_id=guild_id, settings=settings,
        user=session["user"],
        warn_count=warn_count, panel_count=panel_count,
        cmd_count=cmd_count, bl_count=bl_count,
        recent_warns=recent_warns, top_cmds=top_cmds,
        recent_audit=recent_audit, sparkline=sparkline, audit_count=audit_count,
    )

# ─────────────────────────────────────────────────────────────
#  SETTINGS
# ─────────────────────────────────────────────────────────────

ALLOWED_SETTINGS = {
    "log_channel", "welcome_channel", "welcome_msg", "mute_role",
    "verify_role", "unverified_role",
    "anti_raid", "raid_threshold", "min_account_age",
    "dj_role",
    "log_msg_delete", "log_msg_edit", "log_member_join",
    "log_member_leave", "log_member_update", "log_voice",
    "log_mod_actions", "log_roles",
    "focus_xp_per_min", "focus_coins_per_min", "focus_max_session_min",
    "focus_min_vc_members", "focus_bonus_multiplier",
    "focus_allowed_role_id", "focus_log_channel_id",
}

@app.route("/dashboard/<guild_id>/settings", methods=["GET", "POST"])
@login_required
@guild_access_required
def guild_settings(guild_id):
    if request.method == "POST":
        d = request.get_json() or {}
        field, value = d.get("field"), d.get("value")
        if field not in ALLOWED_SETTINGS:
            return jsonify({"ok": False, "error": "Invalid field"}), 400
        run_async(db_execute(
            f"UPDATE guild_settings SET {field}=? WHERE guild_id=?",
            (None if value == "" else value, guild_id)
        ))
        return jsonify({"ok": True})
    settings = run_async(db_fetchone("SELECT * FROM guild_settings WHERE guild_id=?", (guild_id,))) or {}
    return render_template("settings.html",
        guild=_guild(guild_id), guild_id=guild_id,
        settings=settings, user=session["user"])


@app.route("/dashboard/<guild_id>/focus")
@login_required
@guild_access_required
def focus_dashboard(guild_id):
    run_async(db_execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (int(guild_id),)))
    settings = run_async(db_fetchone("SELECT * FROM guild_settings WHERE guild_id=?", (int(guild_id),))) or {}
    blocked = run_async(db_fetch(
        "SELECT channel_id FROM focus_blocked_channels WHERE guild_id=? ORDER BY channel_id",
        (int(guild_id),),
    ))
    return render_template(
        "focus.html",
        guild=_guild(guild_id),
        guild_id=guild_id,
        user=session["user"],
        settings=settings,
        blocked=blocked,
    )

# ─────────────────────────────────────────────────────────────
#  MODERATION
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/moderation")
@login_required
@guild_access_required
def moderation(guild_id):
    page = max(1, int(request.args.get("page", 1)))
    per  = 20
    q    = request.args.get("q", "").strip()
    off  = (page - 1) * per

    if q:
        try: uid = int(q)
        except: uid = 0
        rows  = run_async(db_fetch("SELECT * FROM warnings WHERE guild_id=? AND (user_id=? OR reason LIKE ?) ORDER BY created_at DESC LIMIT ? OFFSET ?", (guild_id, uid, f"%{q}%", per, off)))
        total = (run_async(db_fetchone("SELECT COUNT(*) as c FROM warnings WHERE guild_id=? AND (user_id=? OR reason LIKE ?)", (guild_id, uid, f"%{q}%"))) or {}).get("c", 0)
    else:
        rows  = run_async(db_fetch("SELECT * FROM warnings WHERE guild_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?", (guild_id, per, off)))
        total = (run_async(db_fetchone("SELECT COUNT(*) as c FROM warnings WHERE guild_id=?", (guild_id,))) or {}).get("c", 0)

    top_warned = run_async(db_fetch("SELECT user_id, COUNT(*) as cnt FROM warnings WHERE guild_id=? GROUP BY user_id ORDER BY cnt DESC LIMIT 5", (guild_id,)))
    return render_template("moderation.html",
        guild=_guild(guild_id), guild_id=guild_id, user=session["user"],
        warnings=rows, page=page, total_pages=max(1, (total + per - 1) // per),
        total_count=total, q=q, top_warned=top_warned)

@app.route("/dashboard/<guild_id>/moderation/warn/delete/<int:warn_id>", methods=["POST"])
@login_required
@guild_access_required
def delete_warning(guild_id, warn_id):
    run_async(db_execute("DELETE FROM warnings WHERE id=? AND guild_id=?", (warn_id, guild_id)))
    return jsonify({"ok": True})

@app.route("/dashboard/<guild_id>/moderation/warn/clear/<int:user_id>", methods=["POST"])
@login_required
@guild_access_required
def clear_user_warnings(guild_id, user_id):
    run_async(db_execute("DELETE FROM warnings WHERE guild_id=? AND user_id=?", (guild_id, user_id)))
    return jsonify({"ok": True})

@app.route("/dashboard/<guild_id>/moderation/clearall", methods=["POST"])
@login_required
@guild_access_required
def clear_all_warnings(guild_id):
    run_async(db_execute("DELETE FROM warnings WHERE guild_id=?", (guild_id,)))
    return jsonify({"ok": True})
@app.route("/dashboard/<guild_id>/moderation/warn/add", methods=["POST"])
@login_required
@guild_access_required
def add_warning_dashboard(guild_id):
    """Issue a warning from the Members page dashboard."""
    d      = request.get_json() or {}
    uid    = d.get("user_id")
    reason = d.get("reason", "No reason provided")
    if not uid:
        return jsonify({"ok": False, "error": "user_id required"}), 400
    try:
        uid = int(uid)
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid user_id"}), 400
    run_async(db_execute(
        "INSERT INTO warnings (guild_id, user_id, mod_id, reason) VALUES (?,?,?,?)",
        (guild_id, uid, session["user"]["id"], reason)
    ))
    run_async(db_execute(
        "INSERT INTO audit_log (guild_id, action, mod_id, target_id, reason) VALUES (?,?,?,?,?)",
        (guild_id, "WARN", session["user"]["id"], uid, f"[Dashboard] {reason}")
    ))
    total = (run_async(db_fetchone(
        "SELECT COUNT(*) as c FROM warnings WHERE guild_id=? AND user_id=?", (guild_id, uid)
    )) or {}).get("c", 0)
    return jsonify({"ok": True, "total": total})

# ─────────────────────────────────────────────────────────────
#  ROLE PANELS
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/roles")
@login_required
@guild_access_required
def role_panels(guild_id):
    panels = run_async(db_fetch("SELECT * FROM role_panels WHERE guild_id=? ORDER BY created_at DESC", (guild_id,)))
    for p in panels:
        p["entries"] = run_async(db_fetch("SELECT * FROM role_panel_entries WHERE panel_id=?", (p["id"],)))
    return render_template("roles.html",
        guild=_guild(guild_id), guild_id=guild_id,
        panels=panels, user=session["user"])

@app.route("/dashboard/<guild_id>/roles/delete/<int:panel_id>", methods=["POST"])
@login_required
@guild_access_required
def delete_panel(guild_id, panel_id):
    run_async(db_execute("DELETE FROM role_panel_entries WHERE panel_id=?", (panel_id,)))
    run_async(db_execute("DELETE FROM role_panels WHERE id=? AND guild_id=?", (panel_id, guild_id)))
    return jsonify({"ok": True})

# ─────────────────────────────────────────────────────────────
#  BLACKLIST
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/blacklist")
@login_required
@guild_access_required
def blacklist(guild_id):
    entries  = run_async(db_fetch("SELECT * FROM blacklist ORDER BY added_at DESC"))
    is_owner = str(session["user"]["id"]) == str(config.OWNER_ID)
    return render_template("blacklist.html",
        guild=_guild(guild_id), guild_id=guild_id,
        entries=entries, user=session["user"], is_owner=is_owner)

@app.route("/dashboard/<guild_id>/blacklist/add", methods=["POST"])
@login_required
@guild_access_required
def blacklist_add(guild_id):
    if str(session["user"]["id"]) != str(config.OWNER_ID):
        return jsonify({"ok": False, "error": "Owner only"}), 403
    d = request.get_json() or {}
    run_async(db_execute(
        "INSERT OR REPLACE INTO blacklist (user_id, reason, added_by) VALUES (?,?,?)",
        (d.get("user_id"), d.get("reason", "No reason"), session["user"]["id"])
    ))
    return jsonify({"ok": True})

@app.route("/dashboard/<guild_id>/blacklist/remove/<int:user_id>", methods=["POST"])
@login_required
@guild_access_required
def blacklist_remove(guild_id, user_id):
    if str(session["user"]["id"]) != str(config.OWNER_ID):
        return jsonify({"ok": False, "error": "Owner only"}), 403
    run_async(db_execute("DELETE FROM blacklist WHERE user_id=?", (user_id,)))
    return jsonify({"ok": True})

# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/audit")
@login_required
@guild_access_required
def audit_log(guild_id):
    page   = max(1, int(request.args.get("page", 1)))
    action = request.args.get("action", "")
    per    = 25
    off    = (page - 1) * per

    if action:
        rows  = run_async(db_fetch("SELECT * FROM audit_log WHERE guild_id=? AND action=? ORDER BY created_at DESC LIMIT ? OFFSET ?", (guild_id, action, per, off)))
        total = (run_async(db_fetchone("SELECT COUNT(*) as c FROM audit_log WHERE guild_id=? AND action=?", (guild_id, action))) or {}).get("c", 0)
    else:
        rows  = run_async(db_fetch("SELECT * FROM audit_log WHERE guild_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?", (guild_id, per, off)))
        total = (run_async(db_fetchone("SELECT COUNT(*) as c FROM audit_log WHERE guild_id=?", (guild_id,))) or {}).get("c", 0)

    action_types = [a["action"] for a in run_async(db_fetch("SELECT DISTINCT action FROM audit_log WHERE guild_id=? ORDER BY action", (guild_id,)))]
    return render_template("audit_log.html",
        guild=_guild(guild_id), guild_id=guild_id, user=session["user"],
        rows=rows, page=page, total_pages=max(1, (total + per - 1) // per),
        total_count=total, action=action, action_types=action_types)

# ─────────────────────────────────────────────────────────────
#  MEMBERS  ← new page
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/members")
@login_required
@guild_access_required
def members(guild_id):
    per   = 50
    after = request.args.get("after", "0")
    members_data = bot_req(f"/guilds/{guild_id}/members?limit={per}&after={after}") or []

    warned_map = {str(r["user_id"]): r["cnt"] for r in
                  run_async(db_fetch("SELECT user_id, COUNT(*) as cnt FROM warnings WHERE guild_id=? GROUP BY user_id", (guild_id,)))}
    bl_set = {str(r["user_id"]) for r in run_async(db_fetch("SELECT user_id FROM blacklist"))}

    for m in members_data:
        uid = str(m["user"]["id"])
        m["warn_count"]    = warned_map.get(uid, 0)
        m["is_blacklisted"] = uid in bl_set

    next_after = members_data[-1]["user"]["id"] if len(members_data) == per else None
    return render_template("members.html",
        guild=_guild(guild_id), guild_id=guild_id, user=session["user"],
        members=members_data, next_after=next_after, after=after)

# ─────────────────────────────────────────────────────────────
#  ANNOUNCEMENTS  ← new page
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/announcements", methods=["GET", "POST"])
@login_required
@guild_access_required
def announcements(guild_id):
    if request.method == "POST":
        d          = request.get_json() or {}
        channel_id = d.get("channel_id")
        title      = d.get("title", "Announcement")
        message    = d.get("message", "")
        ping       = d.get("ping", "none")

        if not channel_id or not message:
            return jsonify({"ok": False, "error": "Channel and message required"}), 400

        try:
            color = int(d.get("color", "3d8bff").lstrip("#"), 16)
        except Exception:
            color = 0x3d8bff

        embed = {
            "title": title, "description": message, "color": color,
            "footer": {"text": f"Sent by {session['user']['username']} via Dashboard"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        content = {"everyone": "@everyone", "here": "@here"}.get(ping, "")
        resp = req.post(
            f"{DISCORD_API}/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {config.TOKEN}", "Content-Type": "application/json"},
            json={"content": content, "embeds": [embed]}, timeout=8
        )
        if resp.ok:
            run_async(db_execute(
                "INSERT INTO audit_log (guild_id, action, mod_id, reason, extra) VALUES (?,?,?,?,?)",
                (guild_id, "ANNOUNCE", session["user"]["id"],
                 f"#{channel_id}: {title}", message[:200])
            ))
            return jsonify({"ok": True, "message_id": resp.json().get("id")})
        return jsonify({"ok": False, "error": resp.json().get("message", "Discord error")}), 400

    channels_raw = bot_req(f"/guilds/{guild_id}/channels") or []
    channels     = sorted([c for c in channels_raw if c["type"] == 0], key=lambda c: c.get("position", 0))
    recent       = run_async(db_fetch("SELECT * FROM audit_log WHERE guild_id=? AND action='ANNOUNCE' ORDER BY created_at DESC LIMIT 10", (guild_id,)))
    return render_template("announcements.html",
        guild=_guild(guild_id), guild_id=guild_id, user=session["user"],
        channels=channels, recent=recent)

# ─────────────────────────────────────────────────────────────
#  API
# ─────────────────────────────────────────────────────────────

@app.route("/api/<guild_id>/stats")
@login_required
def api_stats(guild_id):
    return jsonify({
        "warnings": (run_async(db_fetchone("SELECT COUNT(*) as c FROM warnings WHERE guild_id=?",    (guild_id,))) or {}).get("c", 0),
        "panels":   (run_async(db_fetchone("SELECT COUNT(*) as c FROM role_panels WHERE guild_id=?", (guild_id,))) or {}).get("c", 0),
        "commands": (run_async(db_fetchone("SELECT COUNT(*) as c FROM command_stats WHERE guild_id=?",(guild_id,))) or {}).get("c", 0),
        "audit":    (run_async(db_fetchone("SELECT COUNT(*) as c FROM audit_log WHERE guild_id=?",   (guild_id,))) or {}).get("c", 0),
    })


# ─────────────────────────────────────────────────────────────
#  ALIASES
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/aliases")
@login_required
@guild_access_required
def aliases(guild_id):
    rows = run_async(db_fetch(
        "SELECT * FROM command_aliases WHERE guild_id=? ORDER BY alias ASC", (guild_id,)
    ))
    all_cmds = ALIAS_COMMANDS
    return render_template("aliases.html",
        guild=_guild(guild_id), guild_id=guild_id, user=session["user"],
        aliases=rows, all_cmds=all_cmds)

@app.route("/dashboard/<guild_id>/aliases/add", methods=["POST"])
@login_required
@guild_access_required
def alias_add(guild_id):
    d = request.get_json() or {}
    alias   = d.get("alias","").lower().strip().lstrip("!/")
    command = d.get("command","").lower().strip().lstrip("/")
    if not alias or not command:
        return jsonify({"ok": False, "error": "Alias and command required"}), 400
    if " " in alias or len(alias) > 30:
        return jsonify({"ok": False, "error": "Alias must be one word, max 30 chars"}), 400
    run_async(db_execute(
        "INSERT OR REPLACE INTO command_aliases (guild_id, alias, command) VALUES (?,?,?)",
        (guild_id, alias, command)
    ))
    return jsonify({"ok": True})

@app.route("/dashboard/<guild_id>/aliases/delete/<path:alias>", methods=["POST"])
@login_required
@guild_access_required
def alias_delete(guild_id, alias):
    run_async(db_execute(
        "DELETE FROM command_aliases WHERE guild_id=? AND alias=?", (guild_id, alias.lower())
    ))
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────
#  TICKET SETTINGS SAVE
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/automod")
@login_required
@guild_access_required
def automod(guild_id):
    import json as _json
    settings = run_async(db_fetchone("SELECT * FROM automod_settings WHERE guild_id=?", (guild_id,))) or {}
    log      = run_async(db_fetch(
        "SELECT * FROM automod_log WHERE guild_id=? ORDER BY created_at DESC LIMIT 50", (guild_id,)
    ))
    stats    = run_async(db_fetch(
        "SELECT rule, COUNT(*) as cnt FROM automod_log WHERE guild_id=? GROUP BY rule ORDER BY cnt DESC",
        (guild_id,)
    ))
    total_actions = (run_async(db_fetchone(
        "SELECT COUNT(*) as c FROM automod_log WHERE guild_id=?", (guild_id,)
    )) or {}).get("c", 0)
    today_actions = (run_async(db_fetchone(
        "SELECT COUNT(*) as c FROM automod_log WHERE guild_id=? AND DATE(created_at)=DATE('now')", (guild_id,)
    )) or {}).get("c", 0)
    bad_words = _json.loads(settings.get("bad_words") or "[]")
    whitelist = _json.loads(settings.get("links_whitelist") or "[]")
    return render_template("automod.html",
        guild=_guild(guild_id), guild_id=guild_id, user=session["user"],
        settings=settings, log=log, stats=stats,
        total_actions=total_actions, today_actions=today_actions,
        bad_words=bad_words, whitelist=whitelist)

@app.route("/dashboard/<guild_id>/automod/save", methods=["POST"])
@login_required
@guild_access_required
def automod_save(guild_id):
    import json as _json
    d = request.get_json() or {}
    ALLOWED_FIELDS = {
        "enabled","spam_enabled","spam_threshold","spam_window","spam_action",
        "links_enabled","links_action","links_whitelist",
        "words_enabled","words_action","bad_words",
        "caps_enabled","caps_threshold","caps_min_length","caps_action",
        "mention_enabled","mention_threshold","mention_action",
        "exempt_roles","exempt_channels"
    }
    run_async(db_execute("INSERT OR IGNORE INTO automod_settings (guild_id) VALUES (?)", (guild_id,)))
    for key, val in d.items():
        if key in ALLOWED_FIELDS:
            run_async(db_execute(
                f"UPDATE automod_settings SET {key}=? WHERE guild_id=?",
                (val if val != "" else None, guild_id)
            ))
    return jsonify({"ok": True})



# ─────────────────────────────────────────────────────────────
#  TEMP ROOMS
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/temprooms")
@login_required
@guild_access_required
def temprooms(guild_id):
    settings     = run_async(db_fetchone("SELECT * FROM temproom_settings WHERE guild_id=?", (guild_id,))) or {}
    active_rooms = run_async(db_fetch("SELECT * FROM temp_rooms WHERE guild_id=? ORDER BY created_at DESC", (guild_id,)))
    return render_template("temprooms.html",
        guild=_guild(guild_id), guild_id=guild_id, user=session["user"],
        settings=settings, rooms=active_rooms)

@app.route("/dashboard/<guild_id>/temprooms/settings", methods=["POST"])
@login_required
@guild_access_required
def temprooms_save(guild_id):
    d = request.get_json() or {}
    ALLOWED = {"enabled","join_channel","category_id","name_template","default_limit","default_bitrate","log_channel"}
    run_async(db_execute("INSERT OR IGNORE INTO temproom_settings (guild_id) VALUES (?)", (guild_id,)))
    for key, val in d.items():
        if key in ALLOWED:
            run_async(db_execute(f"UPDATE temproom_settings SET {key}=? WHERE guild_id=?",
                (None if val == "" else val, guild_id)))
    return jsonify({"ok": True})

@app.route("/dashboard/<guild_id>/temprooms/kick/<int:channel_id>/<int:user_id>", methods=["POST"])
@login_required
@guild_access_required
def temproom_kick(guild_id, channel_id, user_id):
    # Mark for kick — bot handles actual voice ops; dashboard can only update DB
    run_async(db_execute("DELETE FROM temp_rooms WHERE channel_id=? AND guild_id=?", (channel_id, guild_id)))
    return jsonify({"ok": True, "note": "Room record removed. Bot will auto-clean the VC."})

# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/export/warnings")
@login_required
@guild_access_required
def export_warnings(guild_id):
    import csv, io
    from flask import Response
    rows = run_async(db_fetch(
        "SELECT id,user_id,mod_id,reason,created_at FROM warnings WHERE guild_id=? ORDER BY created_at DESC",
        (guild_id,)))
    buf = io.StringIO()
    w   = csv.DictWriter(buf, fieldnames=["id","user_id","mod_id","reason","created_at"])
    w.writeheader()
    w.writerows(rows)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=warnings_{guild_id}.csv"})

@app.route("/dashboard/<guild_id>/search")
@login_required
@guild_access_required
def user_search(guild_id):
    uid = request.args.get("uid", "").strip()
    result = {}
    if uid:
        try:
            user_id = int(uid)
            result["warnings"] = run_async(db_fetch(
                "SELECT * FROM warnings WHERE guild_id=? AND user_id=? ORDER BY created_at DESC",
                (guild_id, user_id))) or []
            result["economy"]  = run_async(db_fetchone(
                "SELECT * FROM economy WHERE guild_id=? AND user_id=?", (guild_id, user_id))) or {}
            result["levels"]   = run_async(db_fetchone(
                "SELECT * FROM levels WHERE guild_id=? AND user_id=?",  (guild_id, user_id))) or {}
            result["audit"]    = run_async(db_fetch(
                "SELECT * FROM audit_log WHERE guild_id=? AND target_id=? ORDER BY created_at DESC LIMIT 10",
                (guild_id, user_id))) or []
            result["user_id"]  = user_id
        except ValueError:
            pass
    return render_template("search.html",
        guild=_guild(guild_id), guild_id=guild_id, user=session["user"],
        result=result, uid=uid)



# ─────────────────────────────────────────────────────────────
#  MUSIC (read-only view — actual playback via bot commands)
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/music")
@login_required
@guild_access_required
def music(guild_id):
    return render_template("music.html",
        guild=_guild(guild_id), guild_id=guild_id, user=session["user"])

# ─────────────────────────────────────────────────────────────
#  SECURITY
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/security")
@login_required
@guild_access_required
def security(guild_id):
    s = run_async(db_fetchone("SELECT * FROM guild_settings WHERE guild_id=?", (guild_id,))) or {}
    return render_template("security.html",
        guild=_guild(guild_id), guild_id=guild_id, user=session["user"], settings=s)

@app.route("/dashboard/<guild_id>/security/save", methods=["POST"])
@login_required
@guild_access_required
def security_save(guild_id):
    d = request.get_json() or {}
    ALLOWED = {"anti_raid","raid_threshold","min_account_age","verify_role","unverified_role"}
    run_async(db_execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (guild_id,)))
    for key, val in d.items():
        if key in ALLOWED:
            run_async(db_execute(f"UPDATE guild_settings SET {key}=? WHERE guild_id=?",
                (None if val == "" else val, guild_id)))
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────
#  ANALYTICS (stub — redirects to dashboard overview)
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/analytics")
@login_required
@guild_access_required
def analytics(guild_id):
    guild        = _guild(guild_id)
    top_cmds     = run_async(db_fetch(
        """SELECT command, COUNT(*) as total FROM command_stats
           WHERE guild_id=? GROUP BY command ORDER BY total DESC LIMIT 10""",
        (int(guild_id),)))
    daily        = run_async(db_fetch(
        """SELECT date(used_at) as day, COUNT(*) as total FROM command_stats
           WHERE guild_id=? AND used_at >= datetime('now','-14 days')
           GROUP BY date(used_at) ORDER BY day ASC""",
        (int(guild_id),)))
    total_cmds   = (run_async(db_fetchone(
        "SELECT COUNT(*) as c FROM command_stats WHERE guild_id=?", (int(guild_id),))) or {}).get("c", 0)
    unique_users = (run_async(db_fetchone(
        "SELECT COUNT(DISTINCT user_id) as c FROM command_stats WHERE guild_id=?", (int(guild_id),))) or {}).get("c", 0)
    total_warns  = (run_async(db_fetchone(
        "SELECT COUNT(*) as c FROM warnings WHERE guild_id=?", (int(guild_id),))) or {}).get("c", 0)
    warn_daily   = run_async(db_fetch(
        """SELECT date(created_at) as day, COUNT(*) as total FROM warnings
           WHERE guild_id=? AND created_at >= datetime('now','-14 days')
           GROUP BY date(created_at) ORDER BY day ASC""",
        (int(guild_id),)))
    afk_count    = (run_async(db_fetchone(
        "SELECT COUNT(*) as c FROM afk_users WHERE guild_id=?", (int(guild_id),))) or {}).get("c", 0)
    return render_template("analytics.html",
        guild=guild, guild_id=guild_id, user=session["user"],
        top_cmds=top_cmds, daily=daily,
        total_cmds=total_cmds, unique_users=unique_users,
        total_warns=total_warns, warn_daily=warn_daily,
        afk_count=afk_count)


# ─────────────────────────────────────────────────────────────
#  LOGGING CONFIG
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/logging")
@login_required
@guild_access_required
def logging_config(guild_id):
    s = run_async(db_fetchone("SELECT * FROM guild_settings WHERE guild_id=?", (guild_id,))) or {}
    return render_template("logging.html",
        guild=_guild(guild_id), guild_id=guild_id, user=session["user"], settings=s)

@app.route("/dashboard/<guild_id>/logging/save", methods=["POST"])
@login_required
@guild_access_required
def logging_save(guild_id):
    d = request.get_json() or {}
    ALLOWED = {"log_channel","log_msg_delete","log_msg_edit","log_member_join",
               "log_member_leave","log_member_update","log_voice","log_mod_actions","log_roles"}
    run_async(db_execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (guild_id,)))
    for key, val in d.items():
        if key in ALLOWED:
            run_async(db_execute(f"UPDATE guild_settings SET {key}=? WHERE guild_id=?",
                (None if val == "" else val, guild_id)))
    return jsonify({"ok": True})

# ─────────────────────────────────────────────────────────────
#  CUSTOM COMMANDS
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/custom-commands")
@login_required
@guild_access_required
def custom_commands(guild_id):
    cmds = run_async(db_fetch(
        "SELECT * FROM custom_commands WHERE guild_id=? ORDER BY trigger", (guild_id,)))
    return render_template("custom_commands.html",
        guild=_guild(guild_id), guild_id=guild_id, user=session["user"], cmds=cmds)

@app.route("/dashboard/<guild_id>/custom-commands/add", methods=["POST"])
@login_required
@guild_access_required
def custom_commands_add(guild_id):
    d = request.get_json() or {}
    trigger  = d.get("trigger","").lower().strip()
    response = d.get("response","").strip()
    embed    = int(d.get("embed", 0))
    color    = d.get("embed_color","#5865F2")
    title    = d.get("embed_title","")
    if not trigger or not response:
        return jsonify({"ok": False, "error": "Trigger and response required"}), 400
    run_async(db_execute(
        "INSERT OR REPLACE INTO custom_commands "
        "(guild_id,trigger,response,embed,embed_color,embed_title,created_by) VALUES (?,?,?,?,?,?,?)",
        (guild_id, trigger, response, embed, color, title, session["user"]["id"])))
    return jsonify({"ok": True})

@app.route("/dashboard/<guild_id>/custom-commands/delete/<trigger>", methods=["POST"])
@login_required
@guild_access_required
def custom_commands_delete(guild_id, trigger):
    run_async(db_execute(
        "DELETE FROM custom_commands WHERE guild_id=? AND trigger=?", (guild_id, trigger)))
    return jsonify({"ok": True})

# ─────────────────────────────────────────────────────────────
#  AUTO-ROLES
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/autoroles")
@login_required
@guild_access_required
def autoroles(guild_id):
    import json as _json
    s = run_async(db_fetchone("SELECT auto_roles FROM guild_settings WHERE guild_id=?", (guild_id,))) or {}
    role_ids = _json.loads(s.get("auto_roles") or "[]")
    return render_template("autoroles.html",
        guild=_guild(guild_id), guild_id=guild_id, user=session["user"], role_ids=role_ids)

@app.route("/dashboard/<guild_id>/autoroles/save", methods=["POST"])
@login_required
@guild_access_required
def autoroles_save(guild_id):
    import json as _json
    d = request.get_json() or {}
    role_ids = d.get("role_ids", [])
    run_async(db_execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (guild_id,)))
    run_async(db_execute("UPDATE guild_settings SET auto_roles=? WHERE guild_id=?",
        (_json.dumps(role_ids), guild_id)))
    return jsonify({"ok": True})

# ─────────────────────────────────────────────────────────────
#  MOD NOTES
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/notes")
@login_required
@guild_access_required
def mod_notes(guild_id):
    uid = request.args.get("uid","").strip()
    notes = []
    if uid:
        try:
            notes = run_async(db_fetch(
                "SELECT * FROM mod_notes WHERE guild_id=? AND user_id=? ORDER BY created_at DESC",
                (guild_id, int(uid))))
        except Exception:
            pass
    return render_template("notes.html",
        guild=_guild(guild_id), guild_id=guild_id, user=session["user"],
        notes=notes, uid=uid)

@app.route("/dashboard/<guild_id>/notes/delete/<int:note_id>", methods=["POST"])
@login_required
@guild_access_required
def note_delete(guild_id, note_id):
    run_async(db_execute(
        "DELETE FROM mod_notes WHERE id=? AND guild_id=?", (note_id, guild_id)))
    return jsonify({"ok": True})

# ─────────────────────────────────────────────────────────────
#  DEVELOPER PANEL (owner only)
# ─────────────────────────────────────────────────────────────

@app.route("/dev")
@login_required
def dev_panel():
    if str(session["user"]["id"]) != str(config.OWNER_ID):
        from flask import abort
        abort(403)
    import time as _time
    # Gather stats across ALL guilds
    total_warnings  = (run_async(db_fetchone("SELECT COUNT(*) as c FROM warnings"))  or {}).get("c",0)
    total_users     = (run_async(db_fetchone("SELECT COUNT(*) as c FROM guild_settings")) or {}).get("c",0)
    total_commands  = (run_async(db_fetchone("SELECT COUNT(*) as c FROM command_stats")) or {}).get("c",0) or 0
    total_custom    = (run_async(db_fetchone("SELECT COUNT(*) as c FROM custom_commands")) or {}).get("c",0)
    total_aliases   = (run_async(db_fetchone("SELECT COUNT(*) as c FROM command_aliases")) or {}).get("c",0)
    top_commands    = run_async(db_fetch(
        "SELECT command, COUNT(*) as total FROM command_stats GROUP BY command ORDER BY total DESC LIMIT 10"))
    recent_audit    = run_async(db_fetch(
        "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 20"))
    guilds_list     = run_async(db_fetch(
        "SELECT guild_id FROM guild_settings ORDER BY guild_id DESC"))
    return render_template("dev.html",
        user=session["user"],
        total_warnings=total_warnings,
        total_guilds=total_users,
        total_commands=total_commands,
        total_custom=total_custom,
        total_aliases=total_aliases,
        top_commands=top_commands,
        recent_audit=recent_audit,
        guilds_list=guilds_list,
    )

@app.route("/dev/api/stats")
@login_required
def dev_api_stats():
    if str(session["user"]["id"]) != str(config.OWNER_ID):
        from flask import abort
        abort(403)
    return jsonify({
        "guilds":   (run_async(db_fetchone("SELECT COUNT(*) as c FROM guild_settings")) or {}).get("c", 0),
        "warnings": (run_async(db_fetchone("SELECT COUNT(*) as c FROM warnings"))       or {}).get("c", 0),
        "commands": (run_async(db_fetchone("SELECT COUNT(*) as c FROM command_stats"))  or {}).get("c", 0) or 0,
    })


@app.route("/api/bot-status")
@login_required
def api_bot_status():
    """
    Lightweight status endpoint polled by the dashboard every 30 s.
    Hits the Discord bot API directly — if it responds, the bot is online.
    Returns latency in ms, guild count, and recent command count.
    """
    import time
    t0   = time.monotonic()
    info = bot_req("/users/@me")
    ms   = round((time.monotonic() - t0) * 1000)

    if not info:
        return jsonify({"online": False, "latency_ms": None, "guilds": 0, "commands_today": 0})

    guilds_raw     = bot_req("/users/@me/guilds?limit=200") or []
    guild_count    = len(guilds_raw)
    commands_today = (run_async(db_fetchone(
        "SELECT COUNT(*) as c FROM command_stats WHERE used_at >= DATE('now')"
    )) or {}).get("c", 0)

    return jsonify({
        "online":         True,
        "latency_ms":     ms,
        "guilds":         guild_count,
        "commands_today": commands_today,
        "bot_tag":        f"{info.get('username', 'Bot')}#{info.get('discriminator', '0')}",
    })


@app.route("/dashboard/<guild_id>/roles/create", methods=["POST"])
@login_required
@guild_access_required
def create_panel(guild_id):
    import json as _json
    d = request.get_json() or {}
    title       = d.get("title", "Role Panel")[:100]
    description = d.get("description", "Click a button to toggle a role.")[:500]
    color_hex   = d.get("color", "5865F2").lstrip("#")
    channel_id  = d.get("channel_id")
    entries     = d.get("entries", [])   # [{role_id, label, emoji, style}]
    if not entries or not channel_id:
        return jsonify({"ok": False, "error": "channel_id and at least one role required"}), 400
    try:
        color_int = int(color_hex, 16)
    except ValueError:
        color_int = 0x5865F2

    creator_id = int(session["user"]["id"])

    # ── Build the Discord embed + buttons payload ─────────────
    # Button styles: 1=Primary(blue) 2=Secondary(grey) 3=Success(green) 4=Danger(red)
    style_map = {1: 1, 2: 2, 3: 3, 4: 4}
    components = []
    row_buttons = []
    for i, entry in enumerate(entries[:25]):
        btn = {
            "type": 2,  # BUTTON
            "style": style_map.get(int(entry.get("style", 1)), 1),
            "label": (entry.get("label") or "Role")[:80],
            "custom_id": f"rolepanel_toggle_{entry.get('role_id', 0)}",
        }
        if entry.get("emoji"):
            btn["emoji"] = {"name": entry["emoji"]}
        row_buttons.append(btn)
        # Discord allows max 5 buttons per action row
        if len(row_buttons) == 5 or i == len(entries) - 1:
            components.append({"type": 1, "components": row_buttons})
            row_buttons = []

    discord_payload = {
        "embeds": [{
            "title": title,
            "description": description,
            "color": color_int,
            "footer": {"text": "Click a button to toggle a role!"},
        }],
        "components": components,
    }

    # ── POST to Discord ───────────────────────────────────────
    disc_resp = req.post(
        f"{DISCORD_API}/channels/{channel_id}/messages",
        headers={"Authorization": f"Bot {config.TOKEN}", "Content-Type": "application/json"},
        json=discord_payload,
        timeout=10,
    )
    if not disc_resp.ok:
        err = disc_resp.json().get("message", "Discord API error")
        return jsonify({"ok": False, "error": f"Could not post to Discord: {err}"}), 400

    message_id = int(disc_resp.json().get("id", 0))

    # ── Save to DB with real message_id ──────────────────────
    panel_id_row = run_async(db_fetchone(
        "INSERT INTO role_panels (guild_id,title,description,color,channel_id,message_id,created_by) "
        "VALUES (?,?,?,?,?,?,?) RETURNING id",
        (guild_id, title, description, color_int, int(channel_id), message_id, creator_id)
    ))
    if not panel_id_row:
        run_async(db_execute(
            "INSERT INTO role_panels (guild_id,title,description,color,channel_id,message_id,created_by) "
            "VALUES (?,?,?,?,?,?,?)",
            (guild_id, title, description, color_int, int(channel_id), message_id, creator_id)
        ))
        panel_id_row = run_async(db_fetchone(
            "SELECT id FROM role_panels WHERE guild_id=? ORDER BY id DESC LIMIT 1", (guild_id,)
        ))
    pid = panel_id_row["id"] if panel_id_row else None
    if not pid:
        return jsonify({"ok": False, "error": "Panel posted to Discord but DB save failed."}), 500

    for i, entry in enumerate(entries[:25]):
        run_async(db_execute(
            "INSERT INTO role_panel_entries (panel_id,role_id,label,emoji,style,position) VALUES (?,?,?,?,?,?)",
            (pid, int(entry.get("role_id", 0)), (entry.get("label") or "Role")[:80],
             entry.get("emoji", "") or None, int(entry.get("style", 1)), i)
        ))

    return jsonify({"ok": True, "panel_id": pid, "message_id": message_id,
                    "note": "Panel posted to Discord successfully!"})


# ─────────────────────────────────────────────────────────────
#  WARN THRESHOLDS
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/warn-thresholds")
@login_required
@guild_access_required
def warn_thresholds(guild_id):
    rows = run_async(db_fetch(
        "SELECT * FROM warn_thresholds WHERE guild_id=? ORDER BY count ASC", (guild_id,)
    ))
    return jsonify(rows)

@app.route("/dashboard/<guild_id>/warn-thresholds/save", methods=["POST"])
@login_required
@guild_access_required
def warn_thresholds_save(guild_id):
    d       = request.get_json() or {}
    count   = d.get("count")
    action  = d.get("action")
    dur     = d.get("duration")
    if not count or action not in ("mute", "kick", "ban"):
        return jsonify({"ok": False, "error": "count and action required"}), 400
    try:
        count = int(count)
        dur   = int(dur) if dur else None
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid values"}), 400
    run_async(db_execute(
        "INSERT OR REPLACE INTO warn_thresholds (guild_id,count,action,duration) VALUES (?,?,?,?)",
        (guild_id, count, action, dur)
    ))
    return jsonify({"ok": True})

@app.route("/dashboard/<guild_id>/warn-thresholds/delete/<int:count>", methods=["POST"])
@login_required
@guild_access_required
def warn_thresholds_delete(guild_id, count):
    run_async(db_execute(
        "DELETE FROM warn_thresholds WHERE guild_id=? AND count=?", (guild_id, count)
    ))
    return jsonify({"ok": True})



def _init_db_sync():
    """Initialize all DB tables when the dashboard starts standalone.
    Safe to call even if the bot has already created them."""
    import asyncio as _asyncio
    import sys as _sys
    # We need to import db from the parent directory
    _sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from utils import db as _db
    loop = _asyncio.new_event_loop()
    try:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        loop.run_until_complete(_db.init_db())
        loop.run_until_complete(_db.init_new_tables())
        loop.run_until_complete(_db.cleanup_removed_features())
        print("  💾  Database ready.")
    finally:
        loop.close()



# ─────────────────────────────────────────────────────────────
#  DISCORD GUILD STATS API  (server stats widget)
# ─────────────────────────────────────────────────────────────

@app.route("/api/<guild_id>/discord-stats")
@login_required
def api_discord_guild_stats(guild_id):
    """Live guild info from Discord Bot API: member count, boost tier, etc."""
    data = bot_req(f"/guilds/{guild_id}?with_counts=true")
    if not data or "id" not in data:
        return jsonify({"ok": False, "error": "Could not fetch guild data"})
    return jsonify({
        "ok":           True,
        "member_count": data.get("approximate_member_count", data.get("member_count", 0)),
        "online_count": data.get("approximate_presence_count", 0),
        "boost_tier":   data.get("premium_tier", 0),
        "boost_count":  data.get("premium_subscription_count", 0),
        "name":         data.get("name", ""),
        "icon":         f"https://cdn.discordapp.com/icons/{guild_id}/{data['icon']}.png" if data.get("icon") else None,
        "verification_level": data.get("verification_level", 0),
        "features":     data.get("features", []),
    })


# ─────────────────────────────────────────────────────────────
#  IPC — DASHBOARD → BOT COMMANDS
# ─────────────────────────────────────────────────────────────

@app.route("/api/ipc/command", methods=["POST"])
@login_required
def ipc_send_command():
    """Send a command to the bot and wait for ACK (up to 8s)."""
    if str(session["user"]["id"]) != str(config.OWNER_ID):
        return jsonify({"ok": False, "error": "Owner only"}), 403

    d      = request.get_json() or {}
    action = d.get("action", "")
    params = d.get("params", {})
    nowait = d.get("nowait", False)  # fire-and-forget for shutdown

    ALLOWED = {
        "reload_cogs", "sync_commands", "set_status", "shutdown",
        "enable_module", "disable_module", "maintenance_mode",
        "clear_stats", "vacuum_db", "get_module_state",
        "post_verify", "send_embed", "announce",
    }
    if action not in ALLOWED:
        return jsonify({"ok": False, "error": f"Unknown action: {action}"}), 400

    if not _IPC_AVAILABLE:
        return jsonify({"ok": False, "error": "IPC files not accessible — check DATA_DIR"}), 503

    cid = dash_send_command(action, params)
    if not cid:
        return jsonify({"ok": False, "error": "Failed to write to IPC queue — check file permissions"}), 500

    # Shutdown: fire-and-forget (bot closes before it can ACK)
    if nowait or action == "shutdown":
        return jsonify({"ok": True, "queued": True, "cmd_id": cid,
                        "msg": "Command queued — bot will execute within 2s."})

    # All other actions: block and wait for bot's ACK
    ack = dash_poll_ack(cid, max_wait=8.0)
    return jsonify({
        "ok":     ack.get("ok", False),
        "cmd_id": cid,
        "msg":    ack.get("msg", "No response"),
        "data":   ack.get("data", {}),
    })


@app.route("/api/ipc/module-state")
@login_required
def api_module_state():
    """Read the last-known module state from disk (written by bot)."""
    state = read_module_state() if _IPC_AVAILABLE else {}
    return jsonify({"ok": True, "modules": state})


# ─────────────────────────────────────────────────────────────
#  SETTINGS — per-field auto-save (JSON body)
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/settings/save", methods=["POST"])
@login_required
@guild_access_required
def settings_save_field(guild_id):
    """Single-field auto-save called by debounced inputs."""
    d = request.get_json() or {}
    ALLOWED = {
        "log_channel", "welcome_channel", "welcome_msg", "mute_role",
        "dj_role", "bot_status", "bot_status_type",
        "log_msg_delete", "log_msg_edit", "log_member_join", "log_member_leave",
        "log_member_update", "log_voice", "log_mod_actions", "log_roles",
    }
    updates = {k: v for k, v in d.items() if k in ALLOWED}
    if not updates:
        return jsonify({"ok": False, "error": "No valid fields"}), 400
    for field, value in updates.items():
        run_async(db_execute(
            f"UPDATE guild_settings SET {field}=? WHERE guild_id=?",
            (None if value == "" else value, guild_id)
        ))
    return jsonify({"ok": True})


@app.route("/dashboard/<guild_id>/focus/settings/save", methods=["POST"])
@login_required
@guild_access_required
def focus_settings_save(guild_id):
    d = request.get_json() or {}
    allowed = {
        "focus_xp_per_min", "focus_coins_per_min", "focus_max_session_min",
        "focus_min_vc_members", "focus_bonus_multiplier",
        "focus_allowed_role_id", "focus_log_channel_id",
    }
    updates = {k: v for k, v in d.items() if k in allowed}
    if not updates:
        return jsonify({"ok": False, "error": "No valid fields"}), 400
    run_async(db_execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (int(guild_id),)))
    for field, value in updates.items():
        run_async(db_execute(
            f"UPDATE guild_settings SET {field}=? WHERE guild_id=?",
            (None if value == "" else value, int(guild_id))
        ))
    return jsonify({"ok": True})


@app.route("/dashboard/<guild_id>/focus/blocked/add", methods=["POST"])
@login_required
@guild_access_required
def focus_blocked_add(guild_id):
    d = request.get_json() or {}
    raw = str(d.get("channel_id", "")).strip()
    if not raw.isdigit():
        return jsonify({"ok": False, "error": "Channel ID must be numeric"}), 400
    run_async(db_execute(
        "INSERT OR IGNORE INTO focus_blocked_channels (channel_id, guild_id) VALUES (?,?)",
        (int(raw), int(guild_id)),
    ))
    return jsonify({"ok": True})


@app.route("/dashboard/<guild_id>/focus/blocked/remove/<int:channel_id>", methods=["POST"])
@login_required
@guild_access_required
def focus_blocked_remove(guild_id, channel_id):
    run_async(db_execute(
        "DELETE FROM focus_blocked_channels WHERE channel_id=? AND guild_id=?",
        (channel_id, int(guild_id)),
    ))
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────
#  ROLE PANEL — reorder entries drag-and-drop
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/roles/reorder", methods=["POST"])
@login_required
@guild_access_required
def reorder_panel_entries(guild_id):
    """Body: { panel_id: int, order: [entry_id, ...] }"""
    d = request.get_json() or {}
    panel_id = d.get("panel_id")
    order    = d.get("order", [])
    if not panel_id or not order:
        return jsonify({"ok": False, "error": "panel_id and order required"}), 400
    panel = run_async(db_fetchone(
        "SELECT id FROM role_panels WHERE id=? AND guild_id=?", (panel_id, guild_id)
    ))
    if not panel:
        return jsonify({"ok": False, "error": "Panel not found"}), 404
    for pos, entry_id in enumerate(order):
        run_async(db_execute(
            "UPDATE role_panel_entries SET position=? WHERE id=? AND panel_id=?",
            (pos, entry_id, panel_id)
        ))
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────
#  SOCKETIO — LIVE LOG STREAM
# ─────────────────────────────────────────────────────────────

_socket_cursors: dict = {}


@socketio.on("connect")
def on_ws_connect():
    """Send last 80 log lines on connect."""
    sid = request.sid
    recent = dash_get_recent_logs(80)
    _socket_cursors[sid] = _get_log_line_count()
    if recent:
        emit("log_batch", {"events": recent})


@socketio.on("disconnect")
def on_ws_disconnect():
    _socket_cursors.pop(request.sid, None)


@socketio.on("subscribe_logs")
def on_subscribe_logs():
    sid = request.sid
    _socket_cursors[sid] = _get_log_line_count()
    emit("subscribed", {"ok": True})


def _get_log_line_count() -> int:
    try:
        from utils.ipc import BOT_TO_DASH
        with open(BOT_TO_DASH, "r", encoding="utf-8") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def _log_broadcast_thread():
    """Background thread: poll IPC file and broadcast new events via SocketIO."""
    last_line = 0
    while True:
        time.sleep(1.5)
        try:
            events, new_line = dash_read_events(last_line)
            if events:
                socketio.emit("log_batch", {"events": events})
            last_line = new_line
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
#  START
# ─────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────
#  AFK DASHBOARD
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/afk")
@login_required
@guild_access_required
def afk_dashboard(guild_id):
    guild   = _guild(guild_id)
    records = run_async(db_fetch(
        "SELECT * FROM afk_users WHERE guild_id=? ORDER BY afk_since DESC",
        (int(guild_id),)
    ))
    return render_template(
        "afk.html",
        guild=guild,
        guild_id=guild_id,
        user=session["user"],
        afk_list=records,
        afk_count=len(records),
    )


@app.route("/dashboard/<guild_id>/afk/remove/<int:user_id>", methods=["POST"])
@login_required
@guild_access_required
def afk_remove(guild_id, user_id):
    run_async(db_execute(
        "DELETE FROM afk_users WHERE guild_id=? AND user_id=?",
        (int(guild_id), user_id)
    ))
    flash("AFK entry removed.", "success")
    return redirect(url_for("afk_dashboard", guild_id=guild_id))


# ─────────────────────────────────────────────────────────────
#  VERIFICATION GATE
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/verification")
@login_required
@guild_access_required
def verification(guild_id):
    guild    = _guild(guild_id)
    settings = run_async(db_fetchone(
        "SELECT * FROM guild_settings WHERE guild_id=?", (int(guild_id),))) or {}
    return render_template("verification.html",
        guild=guild, guild_id=guild_id,
        user=session["user"], settings=settings)


@app.route("/dashboard/<guild_id>/verification/save", methods=["POST"])
@login_required
@guild_access_required
def verification_save(guild_id):
    d = request.get_json() or {}
    run_async(db_execute(
        "INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (int(guild_id),)))
    allowed = {"verify_role", "unverified_role", "anti_raid", "raid_threshold", "min_account_age"}
    for key, val in d.items():
        if key in allowed:
            run_async(db_execute(
                f"UPDATE guild_settings SET {key}=? WHERE guild_id=?",
                (None if val == "" else val, int(guild_id))))
    return jsonify({"ok": True})


@app.route("/dashboard/<guild_id>/verification/post", methods=["POST"])
@login_required
@guild_access_required
def verification_post(guild_id):
    d          = request.get_json() or {}
    channel_id = d.get("channel_id")
    if not channel_id:
        return jsonify({"ok": False, "error": "channel_id required"}), 400
    if _IPC_AVAILABLE:
        cid = dash_send_command("post_verify", {"guild_id": int(guild_id), "channel_id": int(channel_id)})
        if cid:
            ack = dash_poll_ack(cid)
            return jsonify({"ok": ack.get("ok", False), "error": ack.get("msg") if not ack.get("ok") else None})
        return jsonify({"ok": False, "error": "Failed to queue command"})
    return jsonify({"ok": False, "error": "IPC not available"})


# ─────────────────────────────────────────────────────────────
#  CUSTOM EMBED BUILDER
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/embed-builder")
@login_required
@guild_access_required
def embed_builder(guild_id):
    guild = _guild(guild_id)
    return render_template("embed_builder.html",
        guild=guild, guild_id=guild_id, user=session["user"])


@app.route("/dashboard/<guild_id>/embed-builder/send", methods=["POST"])
@login_required
@guild_access_required
def embed_builder_send(guild_id):
    d = request.get_json() or {}
    channel_id = d.get("channel_id")
    embed_data  = d.get("embed", {})
    if not channel_id or not embed_data:
        return jsonify({"ok": False, "error": "channel_id and embed required"}), 400
    if _IPC_AVAILABLE:
        cid = dash_send_command("send_embed", {
            "guild_id":   int(guild_id),
            "channel_id": int(channel_id),
            "embed":      embed_data,
        })
        if cid:
            ack = dash_poll_ack(cid)
            return jsonify({"ok": ack.get("ok", False), "error": ack.get("msg") if not ack.get("ok") else None})
        return jsonify({"ok": False, "error": "Failed to queue command"})
    return jsonify({"ok": False, "error": "IPC not available"})


# ─────────────────────────────────────────────────────────────
#  LIVE STATS API
# ─────────────────────────────────────────────────────────────

@app.route("/api/<guild_id>/live-stats")
@login_required
def api_live_stats(guild_id):
    try:
        gid = int(guild_id)
    except ValueError:
        return jsonify({"error": "invalid guild_id"}), 400

    total_cmds   = (run_async(db_fetchone("SELECT COUNT(*) as c FROM command_stats WHERE guild_id=?", (gid,))) or {}).get("c", 0)
    cmds_today   = (run_async(db_fetchone("SELECT COUNT(*) as c FROM command_stats WHERE guild_id=? AND date(used_at)=date('now')", (gid,))) or {}).get("c", 0)
    total_warns  = (run_async(db_fetchone("SELECT COUNT(*) as c FROM warnings WHERE guild_id=?", (gid,))) or {}).get("c", 0)
    warns_today  = (run_async(db_fetchone("SELECT COUNT(*) as c FROM warnings WHERE guild_id=? AND date(created_at)=date('now')", (gid,))) or {}).get("c", 0)
    afk_count    = (run_async(db_fetchone("SELECT COUNT(*) as c FROM afk_users WHERE guild_id=?", (gid,))) or {}).get("c", 0)
    temp_rooms   = (run_async(db_fetchone("SELECT COUNT(*) as c FROM temp_rooms WHERE guild_id=?", (gid,))) or {}).get("c", 0)
    bl_count     = (run_async(db_fetchone("SELECT COUNT(*) as c FROM blacklist", ())) or {}).get("c", 0)
    daily = run_async(db_fetch(
        "SELECT date(used_at) as day, COUNT(*) as total FROM command_stats "
        "WHERE guild_id=? AND used_at >= datetime('now','-7 days') "
        "GROUP BY date(used_at) ORDER BY day ASC", (gid,)))

    return jsonify({
        "ok": True,
        "total_cmds": total_cmds, "cmds_today": cmds_today,
        "total_warns": total_warns, "warns_today": warns_today,
        "afk_count": afk_count,
        "temp_rooms": temp_rooms, "bl_count": bl_count,
        "sparkline": [{"day": r["day"], "total": r["total"]} for r in daily],
    })


# ─────────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _init_db_sync()
    t = threading.Thread(target=_log_broadcast_thread, daemon=True)
    t.start()
    print("  📡  IPC log broadcast thread started.")
    socketio.run(
        app,
        host=config.DASHBOARD_HOST,
        port=config.DASHBOARD_PORT,
        debug=True,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )
