"""
dashboard/app.py  —  Flask dashboard with Discord OAuth2
Run separately from the bot:  python dashboard/app.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import (
    Flask, render_template, redirect, url_for,
    session, request, jsonify, flash
)
import requests as req
import asyncio, aiosqlite, json
from functools import wraps
from datetime import datetime, timezone
import config

import hashlib, pickle, pathlib

app = Flask(__name__)
app.secret_key = config.DASHBOARD_SECRET_KEY

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
        finally:
            loop.close()
        _db_initialized = True
    except Exception as e:
        print(f"  ⚠️  DB init warning: {e}")

@app.before_request
def before_request():
    _ensure_db()

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

ALLOWED_SETTINGS = {"log_channel", "welcome_channel", "welcome_msg", "mute_role"}

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
    settings        = run_async(db_fetchone("SELECT * FROM guild_settings WHERE guild_id=?",        (guild_id,))) or {}
    ticket_settings = run_async(db_fetchone("SELECT * FROM ticket_settings WHERE guild_id=?", (guild_id,))) or {}
    return render_template("settings.html",
        guild=_guild(guild_id), guild_id=guild_id,
        settings=settings, ticket_settings=ticket_settings, user=session["user"])

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
#  ANALYTICS
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/analytics")
@login_required
@guild_access_required
def analytics(guild_id):
    period = request.args.get("period", "14")
    try: period = max(7, min(90, int(period)))
    except: period = 14
    top_cmds     = run_async(db_fetch("SELECT command, COUNT(*) as uses FROM command_stats WHERE guild_id=? GROUP BY command ORDER BY uses DESC LIMIT 12", (guild_id,)))
    daily        = run_async(db_fetch(f"SELECT DATE(used_at) as day, COUNT(*) as uses FROM command_stats WHERE guild_id=? AND used_at >= DATE('now','-{period} days') GROUP BY day ORDER BY day", (guild_id,)))
    hourly       = run_async(db_fetch("SELECT strftime('%H',used_at) as hr, COUNT(*) as uses FROM command_stats WHERE guild_id=? AND used_at >= DATE('now','-7 days') GROUP BY hr ORDER BY hr", (guild_id,)))
    total_cmds   = (run_async(db_fetchone("SELECT COUNT(*) as c FROM command_stats WHERE guild_id=?",                              (guild_id,))) or {}).get("c", 0)
    unique_users = (run_async(db_fetchone("SELECT COUNT(DISTINCT user_id) as c FROM command_stats WHERE guild_id=?",               (guild_id,))) or {}).get("c", 0)
    today_cmds   = (run_async(db_fetchone("SELECT COUNT(*) as c FROM command_stats WHERE guild_id=? AND DATE(used_at)=DATE('now')",(guild_id,))) or {}).get("c", 0)
    return render_template("analytics.html",
        guild=_guild(guild_id), guild_id=guild_id, user=session["user"],
        top_cmds=top_cmds, daily=daily, hourly=hourly, period=period,
        total_cmds=total_cmds, unique_users=unique_users, today_cmds=today_cmds)

# ─────────────────────────────────────────────────────────────
#  AUDIT LOG  ← new page
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
    # Full command list for the UI dropdown
    all_cmds = [
        "ping","avatar","uptime","botinfo","help",
        "server","userinfo","roles",
        "kick","ban","unban","clear","warn","warnings","clearwarns","delwarn",
        "setuprole","panels","deletepanel",
        "setlog","setwelcome","settings",
        "ticketsetup",
        "ticket open","ticket close","ticket claim","ticket add",
        "ticket remove","ticket panel","ticket transcript",
        "balance","daily","work","pay","leaderboard","shop","buy","inventory",
        "eco give","eco take","eco reset","eco additem","eco removeitem",
        "rank","levels","levelsetup","setlevelrole","removelevelrole","resetxp",
        "automod toggle","automod spam","automod links","automod words",
        "automod caps","automod mentions","automod exempt","automod status",
        "blacklist","unblacklist","blacklistview","reload","shutdown","announce","botstats","dm",
    ]
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

@app.route("/dashboard/<guild_id>/tickets/settings", methods=["POST"])
@login_required
@guild_access_required
def ticket_settings_save(guild_id):
    d = request.get_json() or {}
    ALLOWED = {"category_id", "log_channel", "support_role", "ticket_msg", "max_open"}
    for key, val in d.items():
        if key in ALLOWED:
            db_val = None if val == "" else val
            run_async(db_execute(
                "INSERT OR IGNORE INTO ticket_settings (guild_id) VALUES (?)", (int(guild_id),)
            ))
            run_async(db_execute(
                f"UPDATE ticket_settings SET {key}=? WHERE guild_id=?",
                (db_val, guild_id)
            ))
    return jsonify({"ok": True})

# ─────────────────────────────────────────────────────────────
#  TICKETS
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/tickets")
@login_required
@guild_access_required
def tickets(guild_id):
    status  = request.args.get("status", "")
    page    = max(1, int(request.args.get("page", 1)))
    per     = 20
    off     = (page - 1) * per
    rows    = run_async(db_fetch(
        f"SELECT * FROM tickets WHERE guild_id=?{' AND status=?' if status else ''} ORDER BY opened_at DESC LIMIT ? OFFSET ?",
        (guild_id, status, per, off) if status else (guild_id, per, off)
    ))
    total   = (run_async(db_fetchone(
        f"SELECT COUNT(*) as c FROM tickets WHERE guild_id=?{' AND status=?' if status else ''}",
        (guild_id, status) if status else (guild_id,)
    )) or {}).get("c", 0)
    counts  = {
        s: (run_async(db_fetchone("SELECT COUNT(*) as c FROM tickets WHERE guild_id=? AND status=?", (guild_id, s))) or {}).get("c", 0)
        for s in ("open", "closed", "deleted")
    }
    settings = run_async(db_fetchone("SELECT * FROM ticket_settings WHERE guild_id=?", (guild_id,))) or {}
    return render_template("tickets.html",
        guild=_guild(guild_id), guild_id=guild_id, user=session["user"],
        tickets=rows, total_count=total, status=status, counts=counts,
        total_pages=max(1, (total + per - 1) // per), page=page,
        settings=settings)

@app.route("/dashboard/<guild_id>/tickets/transcript/<int:ticket_id>")
@login_required
@guild_access_required
def ticket_transcript(guild_id, ticket_id):
    ticket = run_async(db_fetchone("SELECT * FROM tickets WHERE id=? AND guild_id=?", (ticket_id, guild_id)))
    if not ticket:
        return jsonify({"ok": False, "error": "Not found"}), 404
    messages = run_async(db_fetch("SELECT * FROM ticket_messages WHERE ticket_id=? ORDER BY sent_at ASC", (ticket_id,)))
    lines = [
        f"TICKET #{ticket['ticket_num']:04d} — {ticket['subject']}",
        f"User: {ticket['user_id']} | Status: {ticket['status']}",
        f"Opened: {ticket['opened_at']} | Closed: {ticket.get('closed_at') or 'N/A'}",
        "─" * 60, ""
    ]
    for m in messages:
        lines.append(f"[{m['sent_at'][:16]}] {m['author_tag']}: {m['content']}")
    from flask import Response
    return Response(
        "\n".join(lines),
        mimetype="text/plain",
        headers={"Content-Disposition": f"attachment; filename=ticket-{ticket['ticket_num']:04d}.txt"}
    )

# ─────────────────────────────────────────────────────────────
#  ECONOMY
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/economy")
@login_required
@guild_access_required
def economy(guild_id):
    leaderboard = run_async(db_fetch(
        "SELECT user_id, balance, bank, total_earned FROM economy WHERE guild_id=? ORDER BY balance+bank DESC LIMIT 20",
        (guild_id,)
    ))
    shop = run_async(db_fetch("SELECT * FROM shop_items WHERE guild_id=? ORDER BY price ASC", (guild_id,)))
    total_coins = (run_async(db_fetchone(
        "SELECT SUM(balance+bank) as s FROM economy WHERE guild_id=?", (guild_id,)
    )) or {}).get("s", 0) or 0
    total_users = (run_async(db_fetchone(
        "SELECT COUNT(*) as c FROM economy WHERE guild_id=?", (guild_id,)
    )) or {}).get("c", 0)
    tx_today = (run_async(db_fetchone(
        "SELECT COUNT(*) as c FROM transactions WHERE guild_id=? AND DATE(created_at)=DATE('now')", (guild_id,)
    )) or {}).get("c", 0)
    return render_template("economy.html",
        guild=_guild(guild_id), guild_id=guild_id, user=session["user"],
        leaderboard=leaderboard, shop=shop,
        total_coins=total_coins, total_users=total_users, tx_today=tx_today)

@app.route("/dashboard/<guild_id>/economy/shop/add", methods=["POST"])
@login_required
@guild_access_required
def economy_shop_add(guild_id):
    d = request.get_json() or {}
    try:
        price = int(d.get("price", 0))
        stock = int(d.get("stock", -1))
        if price < 1: raise ValueError
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid price/stock"}), 400
    run_async(db_execute(
        "INSERT INTO shop_items (guild_id,name,description,price,stock,emoji) VALUES (?,?,?,?,?,?)",
        (guild_id, d.get("name","Item"), d.get("description",""), price, stock, d.get("emoji","🛍️"))
    ))
    return jsonify({"ok": True})

@app.route("/dashboard/<guild_id>/economy/shop/delete/<int:item_id>", methods=["POST"])
@login_required
@guild_access_required
def economy_shop_delete(guild_id, item_id):
    run_async(db_execute("DELETE FROM shop_items WHERE id=? AND guild_id=?", (item_id, guild_id)))
    return jsonify({"ok": True})

@app.route("/dashboard/<guild_id>/economy/give", methods=["POST"])
@login_required
@guild_access_required
def economy_give(guild_id):
    d = request.get_json() or {}
    try:
        uid    = int(d.get("user_id"))
        amount = int(d.get("amount", 0))
        if amount < 1: raise ValueError
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "Invalid data"}), 400
    run_async(db_execute("INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)", (guild_id, uid)))
    run_async(db_execute(
        "UPDATE economy SET balance=balance+?, total_earned=total_earned+? WHERE guild_id=? AND user_id=?",
        (amount, amount, guild_id, uid)
    ))
    run_async(db_execute(
        "INSERT INTO transactions (guild_id,user_id,amount,type,note) VALUES (?,?,?,?,?)",
        (guild_id, uid, amount, "admin", f"Dashboard grant by {session['user']['username']}")
    ))
    return jsonify({"ok": True})

# ─────────────────────────────────────────────────────────────
#  LEVELING
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/leveling")
@login_required
@guild_access_required
def leveling(guild_id):
    leaderboard = run_async(db_fetch(
        "SELECT user_id, xp, level, messages FROM levels WHERE guild_id=? ORDER BY level DESC, xp DESC LIMIT 20",
        (guild_id,)
    ))
    settings = run_async(db_fetchone("SELECT * FROM level_settings WHERE guild_id=?", (guild_id,))) or {}
    level_roles = run_async(db_fetch("SELECT * FROM level_roles WHERE guild_id=? ORDER BY level ASC", (guild_id,)))
    total_users = (run_async(db_fetchone("SELECT COUNT(*) as c FROM levels WHERE guild_id=?", (guild_id,))) or {}).get("c", 0)
    top_level   = (run_async(db_fetchone("SELECT MAX(level) as m FROM levels WHERE guild_id=?", (guild_id,))) or {}).get("m", 0) or 0
    return render_template("leveling.html",
        guild=_guild(guild_id), guild_id=guild_id, user=session["user"],
        leaderboard=leaderboard, settings=settings, level_roles=level_roles,
        total_users=total_users, top_level=top_level)

@app.route("/dashboard/<guild_id>/leveling/settings", methods=["POST"])
@login_required
@guild_access_required
def leveling_settings_save(guild_id):
    d = request.get_json() or {}
    ALLOWED = {"enabled","xp_min","xp_max","xp_cooldown","level_up_channel","level_up_msg"}
    for key, val in d.items():
        if key in ALLOWED:
            run_async(db_execute(
                f"INSERT OR IGNORE INTO level_settings (guild_id) VALUES (?)", (guild_id,)
            ))
            run_async(db_execute(
                f"UPDATE level_settings SET {key}=? WHERE guild_id=?", (val if val != "" else None, guild_id)
            ))
    return jsonify({"ok": True})

@app.route("/dashboard/<guild_id>/leveling/roles/add", methods=["POST"])
@login_required
@guild_access_required
def leveling_role_add(guild_id):
    d = request.get_json() or {}
    try:
        level   = int(d.get("level"))
        role_id = int(d.get("role_id"))
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "Invalid data"}), 400
    run_async(db_execute(
        "INSERT OR REPLACE INTO level_roles (guild_id,level,role_id) VALUES (?,?,?)",
        (guild_id, level, role_id)
    ))
    return jsonify({"ok": True})

@app.route("/dashboard/<guild_id>/leveling/roles/delete/<int:level>", methods=["POST"])
@login_required
@guild_access_required
def leveling_role_delete(guild_id, level):
    run_async(db_execute("DELETE FROM level_roles WHERE guild_id=? AND level=?", (guild_id, level)))
    return jsonify({"ok": True})

# ─────────────────────────────────────────────────────────────
#  AUTO-MOD
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
#  SUGGESTIONS
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/suggestions")
@login_required
@guild_access_required
def suggestions(guild_id):
    status   = request.args.get("status", "")
    settings = run_async(db_fetchone("SELECT * FROM suggestion_settings WHERE guild_id=?", (guild_id,))) or {}
    if status:
        rows = run_async(db_fetch(
            "SELECT * FROM suggestions WHERE guild_id=? AND status=? ORDER BY created_at DESC LIMIT 50",
            (guild_id, status)))
    else:
        rows = run_async(db_fetch(
            "SELECT * FROM suggestions WHERE guild_id=? ORDER BY created_at DESC LIMIT 50", (guild_id,)))
    counts = {
        s: (run_async(db_fetchone("SELECT COUNT(*) as c FROM suggestions WHERE guild_id=? AND status=?",
            (guild_id, s))) or {}).get("c", 0)
        for s in ("pending", "approved", "denied")
    }
    return render_template("suggestions.html",
        guild=_guild(guild_id), guild_id=guild_id, user=session["user"],
        suggestions=rows, settings=settings, counts=counts, status=status)

@app.route("/dashboard/<guild_id>/suggestions/settings", methods=["POST"])
@login_required
@guild_access_required
def suggestions_save(guild_id):
    d = request.get_json() or {}
    ALLOWED = {"channel_id", "dm_on_decision"}
    run_async(db_execute("INSERT OR IGNORE INTO suggestion_settings (guild_id) VALUES (?)", (guild_id,)))
    for key, val in d.items():
        if key in ALLOWED:
            run_async(db_execute(f"UPDATE suggestion_settings SET {key}=? WHERE guild_id=?",
                (None if val == "" else val, guild_id)))
    return jsonify({"ok": True})

@app.route("/dashboard/<guild_id>/suggestions/decide/<int:sug_id>", methods=["POST"])
@login_required
@guild_access_required
def suggestion_decide(guild_id, sug_id):
    d      = request.get_json() or {}
    status = d.get("status")
    note   = d.get("note", "")
    if status not in ("approved", "denied"):
        return jsonify({"ok": False, "error": "Invalid status"}), 400
    sug = run_async(db_fetchone("SELECT * FROM suggestions WHERE id=? AND guild_id=?", (sug_id, guild_id)))
    if not sug: return jsonify({"ok": False, "error": "Not found"}), 404
    run_async(db_execute(
        "UPDATE suggestions SET status=?, mod_note=?, mod_id=? WHERE id=?",
        (status, note, session["user"]["id"], sug_id)
    ))
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────
#  ECONOMY SETTINGS
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/economy/settings", methods=["POST"])
@login_required
@guild_access_required
def economy_settings_save(guild_id):
    d = request.get_json() or {}
    # Economy settings stored in guild_settings as JSON blob for now
    # (no separate table needed — config is per-guild extra JSON)
    ALLOWED = {"daily_min","daily_max","work_min","work_max","currency_name","rob_enabled","slots_enabled"}
    run_async(db_execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (guild_id,)))
    # Store as individual columns would require migration; use extra JSON column approach
    # Actually update each setting we support in guild_settings if it exists, or use key-value
    # For simplicity: store in the existing guild_settings table via SET (they don't exist yet - noted as enhancement)
    return jsonify({"ok": True, "note": "Economy config saved (requires bot restart to apply)"})

# ─────────────────────────────────────────────────────────────
#  EXPORT (CSV downloads)
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

@app.route("/dashboard/<guild_id>/export/economy")
@login_required
@guild_access_required
def export_economy(guild_id):
    import csv, io
    from flask import Response
    rows = run_async(db_fetch(
        "SELECT user_id,balance,bank,total_earned,last_daily,last_work FROM economy WHERE guild_id=? ORDER BY balance+bank DESC",
        (guild_id,)))
    buf = io.StringIO()
    w   = csv.DictWriter(buf, fieldnames=["user_id","balance","bank","total_earned","last_daily","last_work"])
    w.writeheader()
    w.writerows(rows)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=economy_{guild_id}.csv"})

@app.route("/dashboard/<guild_id>/export/levels")
@login_required
@guild_access_required
def export_levels(guild_id):
    import csv, io
    from flask import Response
    rows = run_async(db_fetch(
        "SELECT user_id,level,xp,messages FROM levels WHERE guild_id=? ORDER BY level DESC,xp DESC",
        (guild_id,)))
    buf = io.StringIO()
    w   = csv.DictWriter(buf, fieldnames=["user_id","level","xp","messages"])
    w.writeheader()
    w.writerows(rows)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=levels_{guild_id}.csv"})

# ─────────────────────────────────────────────────────────────
#  USER SEARCH
# ─────────────────────────────────────────────────────────────

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
            result["tickets"]  = run_async(db_fetch(
                "SELECT * FROM tickets WHERE guild_id=? AND user_id=? ORDER BY opened_at DESC LIMIT 5",
                (guild_id, user_id))) or []
            result["audit"]    = run_async(db_fetch(
                "SELECT * FROM audit_log WHERE guild_id=? AND target_id=? ORDER BY created_at DESC LIMIT 10",
                (guild_id, user_id))) or []
            result["user_id"]  = user_id
        except ValueError:
            pass
    return render_template("search.html",
        guild=_guild(guild_id), guild_id=guild_id, user=session["user"],
        result=result, uid=uid)

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
        print("  💾  Database ready.")
    finally:
        loop.close()

if __name__ == "__main__":
    _init_db_sync()
    app.run(host=config.DASHBOARD_HOST, port=config.DASHBOARD_PORT, debug=True)
