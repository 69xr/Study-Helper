"""
utils/db.py  —  Async SQLite database manager
All DB access goes through this module. Each method opens its own
connection so there are no cross-thread/cross-task issues.
"""
import aiosqlite
import asyncio
from config import DB_PATH


# ═══════════════════════════════════════════════════════════════
#  SCHEMA
# ═══════════════════════════════════════════════════════════════

SCHEMA = """
PRAGMA journal_mode=WAL;

-- Per-guild settings
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id     INTEGER PRIMARY KEY,
    prefix       TEXT    DEFAULT '!',
    log_channel  INTEGER DEFAULT NULL,
    mute_role    INTEGER DEFAULT NULL,
    welcome_channel INTEGER DEFAULT NULL,
    welcome_msg  TEXT    DEFAULT 'Welcome {user} to {server}!',
    created_at   TEXT    DEFAULT (datetime('now'))
);

-- Moderation: warnings
CREATE TABLE IF NOT EXISTS warnings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    mod_id     INTEGER NOT NULL,
    reason     TEXT    NOT NULL,
    created_at TEXT    DEFAULT (datetime('now'))
);

-- Role panels (persistent across restarts)
CREATE TABLE IF NOT EXISTS role_panels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    channel_id  INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    title       TEXT    NOT NULL,
    description TEXT,
    color       INTEGER DEFAULT 5592818,
    created_by  INTEGER NOT NULL,
    created_at  TEXT    DEFAULT (datetime('now'))
);

-- Role panel entries (which roles belong to which panel)
CREATE TABLE IF NOT EXISTS role_panel_entries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    panel_id   INTEGER NOT NULL REFERENCES role_panels(id) ON DELETE CASCADE,
    role_id    INTEGER NOT NULL,
    emoji      TEXT    DEFAULT NULL,
    style      INTEGER DEFAULT 1
);

-- Blacklisted users (bot-wide)
CREATE TABLE IF NOT EXISTS blacklist (
    user_id    INTEGER PRIMARY KEY,
    reason     TEXT    NOT NULL,
    added_by   INTEGER NOT NULL,
    added_at   TEXT    DEFAULT (datetime('now'))
);

-- Audit log (mod actions: kick, ban, warn, unban, etc.)
CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    action     TEXT    NOT NULL,
    mod_id     INTEGER NOT NULL,
    target_id  INTEGER,
    reason     TEXT,
    extra      TEXT    DEFAULT NULL,
    created_at TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_guild ON audit_log(guild_id);

-- Command usage stats
CREATE TABLE IF NOT EXISTS command_stats (
    command    TEXT    NOT NULL,
    guild_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    used_at    TEXT    DEFAULT (datetime('now'))
);
"""


# ═══════════════════════════════════════════════════════════════
#  INIT
# ═══════════════════════════════════════════════════════════════

async def init_db() -> None:
    """Create all tables if they don't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


# ═══════════════════════════════════════════════════════════════
#  GUILD SETTINGS
# ═══════════════════════════════════════════════════════════════

async def ensure_guild(guild_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)",
            (guild_id,)
        )
        await db.commit()


async def get_guild_settings(guild_id: int) -> dict | None:
    await ensure_guild(guild_id)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def set_guild_setting(guild_id: int, key: str, value) -> None:
    ALLOWED = {"prefix", "log_channel", "mute_role", "welcome_channel", "welcome_msg"}
    if key not in ALLOWED:
        raise ValueError(f"Unknown setting: {key}")
    await ensure_guild(guild_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE guild_settings SET {key} = ? WHERE guild_id = ?",
            (value, guild_id)
        )
        await db.commit()


# ═══════════════════════════════════════════════════════════════
#  WARNINGS
# ═══════════════════════════════════════════════════════════════

async def add_warning(guild_id: int, user_id: int, mod_id: int, reason: str) -> int:
    """Add a warning. Returns the new total warn count for this user."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO warnings (guild_id, user_id, mod_id, reason) VALUES (?,?,?,?)",
            (guild_id, user_id, mod_id, reason)
        )
        await db.commit()
        async with db.execute(
            "SELECT COUNT(*) FROM warnings WHERE guild_id=? AND user_id=?",
            (guild_id, user_id)
        ) as cur:
            row = await cur.fetchone()
            return row[0]


async def get_warnings(guild_id: int, user_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM warnings WHERE guild_id=? AND user_id=? ORDER BY created_at DESC",
            (guild_id, user_id)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def clear_warnings(guild_id: int, user_id: int) -> int:
    """Remove all warnings for a user. Returns how many were deleted."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM warnings WHERE guild_id=? AND user_id=?",
            (guild_id, user_id)
        ) as cur:
            count = (await cur.fetchone())[0]
        await db.execute(
            "DELETE FROM warnings WHERE guild_id=? AND user_id=?",
            (guild_id, user_id)
        )
        await db.commit()
        return count


async def remove_warning(warning_id: int, guild_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM warnings WHERE id=? AND guild_id=?",
            (warning_id, guild_id)
        ) as cur:
            if not await cur.fetchone():
                return False
        await db.execute("DELETE FROM warnings WHERE id=?", (warning_id,))
        await db.commit()
        return True


# ═══════════════════════════════════════════════════════════════
#  ROLE PANELS
# ═══════════════════════════════════════════════════════════════

async def save_role_panel(
    guild_id: int, channel_id: int, message_id: int,
    title: str, description: str, color: int, created_by: int,
    role_entries: list[dict]   # [{"role_id": int, "emoji": str|None, "style": int}]
) -> int:
    """Save a role panel and return its DB id."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO role_panels
               (guild_id, channel_id, message_id, title, description, color, created_by)
               VALUES (?,?,?,?,?,?,?)""",
            (guild_id, channel_id, message_id, title, description, color, created_by)
        )
        panel_id = cur.lastrowid
        for entry in role_entries:
            await db.execute(
                "INSERT INTO role_panel_entries (panel_id, role_id, emoji, style) VALUES (?,?,?,?)",
                (panel_id, entry["role_id"], entry.get("emoji"), entry.get("style", 1))
            )
        await db.commit()
        return panel_id


async def get_all_role_panels(guild_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM role_panels WHERE guild_id=? ORDER BY created_at DESC",
            (guild_id,)
        ) as cur:
            panels = [dict(r) for r in await cur.fetchall()]
        for panel in panels:
            async with db.execute(
                "SELECT * FROM role_panel_entries WHERE panel_id=?",
                (panel["id"],)
            ) as cur:
                panel["entries"] = [dict(r) for r in await cur.fetchall()]
        return panels


async def delete_role_panel(panel_id: int, guild_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM role_panels WHERE id=? AND guild_id=?",
            (panel_id, guild_id)
        ) as cur:
            if not await cur.fetchone():
                return False
        await db.execute("DELETE FROM role_panel_entries WHERE panel_id=?", (panel_id,))
        await db.execute("DELETE FROM role_panels WHERE id=?", (panel_id,))
        await db.commit()
        return True


async def get_all_panels_for_restore() -> list[dict]:
    """Called on bot startup to re-register all persistent views."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM role_panels") as cur:
            panels = [dict(r) for r in await cur.fetchall()]
        for panel in panels:
            async with db.execute(
                "SELECT * FROM role_panel_entries WHERE panel_id=?",
                (panel["id"],)
            ) as cur:
                panel["entries"] = [dict(r) for r in await cur.fetchall()]
        return panels


# ═══════════════════════════════════════════════════════════════
#  BLACKLIST
# ═══════════════════════════════════════════════════════════════

async def add_to_blacklist(user_id: int, reason: str, added_by: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO blacklist (user_id, reason, added_by) VALUES (?,?,?)",
            (user_id, reason, added_by)
        )
        await db.commit()


async def remove_from_blacklist(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM blacklist WHERE user_id=?", (user_id,)) as cur:
            if not await cur.fetchone():
                return False
        await db.execute("DELETE FROM blacklist WHERE user_id=?", (user_id,))
        await db.commit()
        return True


async def is_blacklisted(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM blacklist WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_blacklist() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM blacklist ORDER BY added_at DESC") as cur:
            return [dict(r) for r in await cur.fetchall()]


# ═══════════════════════════════════════════════════════════════
#  STATS
# ═══════════════════════════════════════════════════════════════

async def log_command(command: str, guild_id: int, user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO command_stats (command, guild_id, user_id) VALUES (?,?,?)",
            (command, guild_id, user_id)
        )
        await db.commit()


async def get_top_commands(limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT command, COUNT(*) as uses
               FROM command_stats GROUP BY command
               ORDER BY uses DESC LIMIT ?""",
            (limit,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_total_commands() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM command_stats") as cur:
            return (await cur.fetchone())[0]


# ═══════════════════════════════════════════════════════════════
#  AUDIT LOG
# ═══════════════════════════════════════════════════════════════

async def log_action(guild_id: int, action: str, mod_id: int,
                     target_id: int = None, reason: str = None, extra: str = None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO audit_log (guild_id, action, mod_id, target_id, reason, extra) VALUES (?,?,?,?,?,?)",
            (guild_id, action, mod_id, target_id, reason, extra)
        )
        await db.commit()


async def get_audit_log(guild_id: int, limit: int = 50, offset: int = 0,
                         action_filter: str = None) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if action_filter:
            query = "SELECT * FROM audit_log WHERE guild_id=? AND action=? ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params = (guild_id, action_filter, limit, offset)
        else:
            query = "SELECT * FROM audit_log WHERE guild_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params = (guild_id, limit, offset)
        async with db.execute(query, params) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_audit_log_count(guild_id: int, action_filter: str = None) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        if action_filter:
            async with db.execute(
                "SELECT COUNT(*) FROM audit_log WHERE guild_id=? AND action=?",
                (guild_id, action_filter)
            ) as cur:
                return (await cur.fetchone())[0]
        else:
            async with db.execute(
                "SELECT COUNT(*) FROM audit_log WHERE guild_id=?", (guild_id,)
            ) as cur:
                return (await cur.fetchone())[0]


# ═══════════════════════════════════════════════════════════════
#  NEW SCHEMA ADDITIONS  (appended, run via ALTER or re-init)
# ═══════════════════════════════════════════════════════════════

NEW_TABLES = """
PRAGMA journal_mode=WAL;

-- ── TICKETS ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ticket_settings (
    guild_id        INTEGER PRIMARY KEY,
    category_id     INTEGER DEFAULT NULL,
    log_channel     INTEGER DEFAULT NULL,
    support_role    INTEGER DEFAULT NULL,
    ticket_msg      TEXT    DEFAULT 'Thank you for opening a ticket. Support will be with you shortly.',
    max_open        INTEGER DEFAULT 1,
    counter         INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    channel_id  INTEGER NOT NULL UNIQUE,
    user_id     INTEGER NOT NULL,
    ticket_num  INTEGER NOT NULL,
    subject     TEXT    DEFAULT 'Support Ticket',
    status      TEXT    DEFAULT 'open',  -- open | closed | deleted
    claimed_by  INTEGER DEFAULT NULL,
    transcript  TEXT    DEFAULT NULL,
    opened_at   TEXT    DEFAULT (datetime('now')),
    closed_at   TEXT    DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_tickets_guild  ON tickets(guild_id);
CREATE INDEX IF NOT EXISTS idx_tickets_user   ON tickets(user_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);

CREATE TABLE IF NOT EXISTS ticket_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id  INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    author_id  INTEGER NOT NULL,
    author_tag TEXT    NOT NULL,
    content    TEXT    NOT NULL,
    sent_at    TEXT    DEFAULT (datetime('now'))
);

-- ── ECONOMY ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS economy (
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    balance     INTEGER DEFAULT 0,
    bank        INTEGER DEFAULT 0,
    total_earned INTEGER DEFAULT 0,
    last_daily  TEXT    DEFAULT NULL,
    last_work   TEXT    DEFAULT NULL,
    PRIMARY KEY (guild_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_econ_guild ON economy(guild_id, balance DESC);

CREATE TABLE IF NOT EXISTS shop_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    name        TEXT    NOT NULL,
    description TEXT    DEFAULT '',
    price       INTEGER NOT NULL,
    role_id     INTEGER DEFAULT NULL,  -- role awarded on purchase
    stock       INTEGER DEFAULT -1,    -- -1 = unlimited
    emoji       TEXT    DEFAULT '🛍️',
    created_at  TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS inventory (
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    item_id     INTEGER NOT NULL REFERENCES shop_items(id) ON DELETE CASCADE,
    quantity    INTEGER DEFAULT 1,
    bought_at   TEXT    DEFAULT (datetime('now')),
    PRIMARY KEY (guild_id, user_id, item_id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    amount      INTEGER NOT NULL,
    type        TEXT    NOT NULL,  -- daily | work | transfer | purchase | admin
    note        TEXT    DEFAULT '',
    created_at  TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tx_guild ON transactions(guild_id);

-- ── LEVELING ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS levels (
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    xp          INTEGER DEFAULT 0,
    level       INTEGER DEFAULT 0,
    messages    INTEGER DEFAULT 0,
    last_xp     TEXT    DEFAULT NULL,  -- cooldown timestamp
    PRIMARY KEY (guild_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_lvl_guild ON levels(guild_id, xp DESC);

CREATE TABLE IF NOT EXISTS level_settings (
    guild_id        INTEGER PRIMARY KEY,
    enabled         INTEGER DEFAULT 1,
    xp_min          INTEGER DEFAULT 15,
    xp_max          INTEGER DEFAULT 35,
    xp_cooldown     INTEGER DEFAULT 60,  -- seconds between XP gains
    level_up_channel INTEGER DEFAULT NULL,
    level_up_msg    TEXT    DEFAULT 'GG {user}! You reached **Level {level}** 🎉',
    no_xp_channels  TEXT    DEFAULT '[]',  -- JSON array of channel IDs
    no_xp_roles     TEXT    DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS level_roles (
    guild_id    INTEGER NOT NULL,
    level       INTEGER NOT NULL,
    role_id     INTEGER NOT NULL,
    PRIMARY KEY (guild_id, level)
);

-- ── AUTO-MOD ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS automod_settings (
    guild_id            INTEGER PRIMARY KEY,
    enabled             INTEGER DEFAULT 0,
    -- spam
    spam_enabled        INTEGER DEFAULT 0,
    spam_threshold      INTEGER DEFAULT 5,   -- messages
    spam_window         INTEGER DEFAULT 5,   -- seconds
    spam_action         TEXT    DEFAULT 'mute',  -- warn|mute|kick|ban
    -- links
    links_enabled       INTEGER DEFAULT 0,
    links_whitelist     TEXT    DEFAULT '[]',    -- JSON
    links_action        TEXT    DEFAULT 'delete',
    -- bad words
    words_enabled       INTEGER DEFAULT 0,
    bad_words           TEXT    DEFAULT '[]',    -- JSON
    words_action        TEXT    DEFAULT 'delete',
    -- caps
    caps_enabled        INTEGER DEFAULT 0,
    caps_threshold      INTEGER DEFAULT 70,      -- percentage
    caps_min_length     INTEGER DEFAULT 10,
    caps_action         TEXT    DEFAULT 'delete',
    -- mentions
    mention_enabled     INTEGER DEFAULT 0,
    mention_threshold   INTEGER DEFAULT 5,
    mention_action      TEXT    DEFAULT 'mute',
    -- exempt
    exempt_roles        TEXT    DEFAULT '[]',
    exempt_channels     TEXT    DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS automod_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    rule        TEXT    NOT NULL,  -- spam|links|words|caps|mentions
    action      TEXT    NOT NULL,
    detail      TEXT    DEFAULT '',
    created_at  TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_aml_guild ON automod_log(guild_id);

-- ── COMMAND ALIASES ─────────────────────────────────────────
-- Prefix-command aliases for slash commands (bot reads these on message)
CREATE TABLE IF NOT EXISTS command_aliases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    alias       TEXT    NOT NULL,        -- e.g.  "bal"
    command     TEXT    NOT NULL,        -- e.g.  "balance"
    created_at  TEXT    DEFAULT (datetime('now')),
    UNIQUE(guild_id, alias)
);
CREATE INDEX IF NOT EXISTS idx_alias_guild ON command_aliases(guild_id);
-- ── TEMP ROOMS ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS temproom_settings (
    guild_id        INTEGER PRIMARY KEY,
    enabled         INTEGER DEFAULT 0,
    join_channel    INTEGER DEFAULT NULL,   -- the "Join to Create" VC
    category_id     INTEGER DEFAULT NULL,   -- where rooms are created
    name_template   TEXT    DEFAULT '{user}''s Room',
    default_limit   INTEGER DEFAULT 0,      -- 0 = unlimited
    default_bitrate INTEGER DEFAULT 64000,
    log_channel     INTEGER DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS temp_rooms (
    channel_id      INTEGER PRIMARY KEY,
    guild_id        INTEGER NOT NULL,
    owner_id        INTEGER NOT NULL,
    name            TEXT    NOT NULL,
    locked          INTEGER DEFAULT 0,
    user_limit      INTEGER DEFAULT 0,
    banned_users    TEXT    DEFAULT '[]',   -- JSON array of user IDs
    created_at      TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tr_guild ON temp_rooms(guild_id);

-- ── SUGGESTIONS ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS suggestion_settings (
    guild_id        INTEGER PRIMARY KEY,
    channel_id      INTEGER DEFAULT NULL,
    results_channel INTEGER DEFAULT NULL,  -- where approved/denied go
    dm_on_decision  INTEGER DEFAULT 1      -- DM author when decided
);

CREATE TABLE IF NOT EXISTS suggestions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id        INTEGER NOT NULL,
    channel_id      INTEGER NOT NULL,
    message_id      INTEGER DEFAULT NULL,
    author_id       INTEGER NOT NULL,
    content         TEXT    NOT NULL,
    status          TEXT    DEFAULT 'pending',  -- pending|approved|denied
    yes_votes       INTEGER DEFAULT 0,
    no_votes        INTEGER DEFAULT 0,
    mod_id          INTEGER DEFAULT NULL,
    mod_note        TEXT    DEFAULT '',
    created_at      TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sug_guild ON suggestions(guild_id);
"""




# ═══════════════════════════════════════════════════════════════
#  COMMAND ALIASES
# ═══════════════════════════════════════════════════════════════

async def get_aliases(guild_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM command_aliases WHERE guild_id=? ORDER BY alias ASC",
            (guild_id,)
        ) as c:
            return [dict(r) for r in await c.fetchall()]

async def set_alias(guild_id: int, alias: str, command: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO command_aliases (guild_id, alias, command) VALUES (?,?,?)",
            (guild_id, alias.lower().strip(), command.lower().strip())
        )
        await db.commit()

async def delete_alias(guild_id: int, alias: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM command_aliases WHERE guild_id=? AND alias=?",
            (guild_id, alias.lower())
        ) as c:
            if not await c.fetchone():
                return False
        await db.execute(
            "DELETE FROM command_aliases WHERE guild_id=? AND alias=?",
            (guild_id, alias.lower())
        )
        await db.commit()
        return True

async def get_alias_command(guild_id: int, alias: str) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT command FROM command_aliases WHERE guild_id=? AND alias=?",
            (guild_id, alias.lower())
        ) as c:
            row = await c.fetchone()
            return row[0] if row else None

async def init_new_tables() -> None:
    """Add the new system tables. Safe to call multiple times."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(NEW_TABLES)
        await db.commit()


# ═══════════════════════════════════════════════════════════════
#  TICKET  DB FUNCTIONS
# ═══════════════════════════════════════════════════════════════

async def get_ticket_settings(guild_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("INSERT OR IGNORE INTO ticket_settings (guild_id) VALUES (?)", (guild_id,))
        await db.commit()
        async with db.execute("SELECT * FROM ticket_settings WHERE guild_id=?", (guild_id,)) as c:
            return dict(await c.fetchone())

async def set_ticket_setting(guild_id: int, key: str, value) -> None:
    ALLOWED = {"category_id","log_channel","support_role","ticket_msg","max_open"}
    if key not in ALLOWED: raise ValueError(f"Bad key: {key}")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO ticket_settings (guild_id) VALUES (?)", (guild_id,))
        await db.execute(f"UPDATE ticket_settings SET {key}=? WHERE guild_id=?", (value, guild_id))
        await db.commit()

async def create_ticket(guild_id: int, channel_id: int, user_id: int, subject: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO ticket_settings (guild_id) VALUES (?)", (guild_id,))
        await db.execute("UPDATE ticket_settings SET counter=counter+1 WHERE guild_id=?", (guild_id,))
        async with db.execute("SELECT counter FROM ticket_settings WHERE guild_id=?", (guild_id,)) as c:
            num = (await c.fetchone())[0]
        cur = await db.execute(
            "INSERT INTO tickets (guild_id,channel_id,user_id,ticket_num,subject) VALUES (?,?,?,?,?)",
            (guild_id, channel_id, user_id, num, subject)
        )
        await db.commit()
        return cur.lastrowid

async def get_ticket_by_channel(channel_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tickets WHERE channel_id=?", (channel_id,)) as c:
            row = await c.fetchone()
            return dict(row) if row else None

async def get_user_open_tickets(guild_id: int, user_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tickets WHERE guild_id=? AND user_id=? AND status='open'",
            (guild_id, user_id)
        ) as c:
            return [dict(r) for r in await c.fetchall()]

async def update_ticket(ticket_id: int, **kwargs) -> None:
    ALLOWED = {"status","claimed_by","transcript","closed_at","subject"}
    sets = ", ".join(f"{k}=?" for k in kwargs if k in ALLOWED)
    vals = [v for k, v in kwargs.items() if k in ALLOWED] + [ticket_id]
    if not sets: return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE tickets SET {sets} WHERE id=?", vals)
        await db.commit()

async def get_guild_tickets(guild_id: int, status: str = None, limit: int = 50, offset: int = 0) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if status:
            async with db.execute(
                "SELECT * FROM tickets WHERE guild_id=? AND status=? ORDER BY opened_at DESC LIMIT ? OFFSET ?",
                (guild_id, status, limit, offset)
            ) as c:
                return [dict(r) for r in await c.fetchall()]
        async with db.execute(
            "SELECT * FROM tickets WHERE guild_id=? ORDER BY opened_at DESC LIMIT ? OFFSET ?",
            (guild_id, limit, offset)
        ) as c:
            return [dict(r) for r in await c.fetchall()]

async def save_ticket_message(ticket_id: int, author_id: int, author_tag: str, content: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO ticket_messages (ticket_id,author_id,author_tag,content) VALUES (?,?,?,?)",
            (ticket_id, author_id, author_tag, content)
        )
        await db.commit()

async def get_ticket_messages(ticket_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM ticket_messages WHERE ticket_id=? ORDER BY sent_at ASC",
            (ticket_id,)
        ) as c:
            return [dict(r) for r in await c.fetchall()]


# ═══════════════════════════════════════════════════════════════
#  ECONOMY  DB FUNCTIONS
# ═══════════════════════════════════════════════════════════════

async def _ensure_econ(db, guild_id: int, user_id: int):
    await db.execute("INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)", (guild_id, user_id))

async def get_balance(guild_id: int, user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await _ensure_econ(db, guild_id, user_id)
        await db.commit()
        async with db.execute("SELECT * FROM economy WHERE guild_id=? AND user_id=?", (guild_id, user_id)) as c:
            return dict(await c.fetchone())

async def add_coins(guild_id: int, user_id: int, amount: int, tx_type: str = "admin", note: str = "") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_econ(db, guild_id, user_id)
        await db.execute(
            "UPDATE economy SET balance=MAX(0,balance+?), total_earned=total_earned+MAX(0,?) WHERE guild_id=? AND user_id=?",
            (amount, amount, guild_id, user_id)
        )
        await db.execute(
            "INSERT INTO transactions (guild_id,user_id,amount,type,note) VALUES (?,?,?,?,?)",
            (guild_id, user_id, amount, tx_type, note)
        )
        await db.commit()
        async with db.execute("SELECT balance FROM economy WHERE guild_id=? AND user_id=?", (guild_id, user_id)) as c:
            return (await c.fetchone())[0]

async def transfer_coins(guild_id: int, from_id: int, to_id: int, amount: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_econ(db, guild_id, from_id)
        await _ensure_econ(db, guild_id, to_id)
        async with db.execute("SELECT balance FROM economy WHERE guild_id=? AND user_id=?", (guild_id, from_id)) as c:
            bal = (await c.fetchone())[0]
        if bal < amount: return False
        await db.execute("UPDATE economy SET balance=balance-? WHERE guild_id=? AND user_id=?", (amount, guild_id, from_id))
        await db.execute("UPDATE economy SET balance=balance+? WHERE guild_id=? AND user_id=?", (amount, guild_id, to_id))
        await db.execute("INSERT INTO transactions (guild_id,user_id,amount,type,note) VALUES (?,?,?,?,?)",
                         (guild_id, from_id, -amount, "transfer", f"→ {to_id}"))
        await db.execute("INSERT INTO transactions (guild_id,user_id,amount,type,note) VALUES (?,?,?,?,?)",
                         (guild_id, to_id, amount, "transfer", f"← {from_id}"))
        await db.commit()
        return True

async def set_last_daily(guild_id: int, user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE economy SET last_daily=datetime('now') WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        await db.commit()

async def set_last_work(guild_id: int, user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE economy SET last_work=datetime('now') WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        await db.commit()

async def get_leaderboard(guild_id: int, limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT user_id, balance, bank, total_earned FROM economy WHERE guild_id=? ORDER BY balance+bank DESC LIMIT ?",
            (guild_id, limit)
        ) as c:
            return [dict(r) for r in await c.fetchall()]

async def get_shop(guild_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM shop_items WHERE guild_id=? AND (stock=-1 OR stock>0) ORDER BY price ASC",
            (guild_id,)
        ) as c:
            return [dict(r) for r in await c.fetchall()]

async def add_shop_item(guild_id: int, name: str, desc: str, price: int,
                         role_id: int = None, stock: int = -1, emoji: str = "🛍️") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO shop_items (guild_id,name,description,price,role_id,stock,emoji) VALUES (?,?,?,?,?,?,?)",
            (guild_id, name, desc, price, role_id, stock, emoji)
        )
        await db.commit()
        return cur.lastrowid

async def remove_shop_item(item_id: int, guild_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM shop_items WHERE id=? AND guild_id=?", (item_id, guild_id)) as c:
            if not await c.fetchone(): return False
        await db.execute("DELETE FROM shop_items WHERE id=?", (item_id,))
        await db.commit()
        return True

async def buy_item(guild_id: int, user_id: int, item_id: int) -> tuple[bool, str]:
    """Returns (success, message)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await _ensure_econ(db, guild_id, user_id)
        async with db.execute("SELECT * FROM shop_items WHERE id=? AND guild_id=?", (item_id, guild_id)) as c:
            item = await c.fetchone()
        if not item: return False, "Item not found."
        item = dict(item)
        if item["stock"] == 0: return False, "Out of stock."
        async with db.execute("SELECT balance FROM economy WHERE guild_id=? AND user_id=?", (guild_id, user_id)) as c:
            bal = (await c.fetchone())[0]
        if bal < item["price"]: return False, f"Not enough coins. Need {item['price']}, have {bal}."
        await db.execute("UPDATE economy SET balance=balance-? WHERE guild_id=? AND user_id=?", (item["price"], guild_id, user_id))
        if item["stock"] > 0:
            await db.execute("UPDATE shop_items SET stock=stock-1 WHERE id=?", (item_id,))
        await db.execute(
            "INSERT INTO inventory (guild_id,user_id,item_id,quantity) VALUES (?,?,?,1) ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET quantity=quantity+1",
            (guild_id, user_id, item_id)
        )
        await db.execute("INSERT INTO transactions (guild_id,user_id,amount,type,note) VALUES (?,?,?,?,?)",
                         (guild_id, user_id, -item["price"], "purchase", item["name"]))
        await db.commit()
        return True, item.get("role_id")

async def get_inventory(guild_id: int, user_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT i.quantity, s.name, s.emoji, s.description, s.role_id
               FROM inventory i JOIN shop_items s ON i.item_id=s.id
               WHERE i.guild_id=? AND i.user_id=?""",
            (guild_id, user_id)
        ) as c:
            return [dict(r) for r in await c.fetchall()]


# ═══════════════════════════════════════════════════════════════
#  LEVELING  DB FUNCTIONS
# ═══════════════════════════════════════════════════════════════

async def get_level_settings(guild_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("INSERT OR IGNORE INTO level_settings (guild_id) VALUES (?)", (guild_id,))
        await db.commit()
        async with db.execute("SELECT * FROM level_settings WHERE guild_id=?", (guild_id,)) as c:
            return dict(await c.fetchone())

async def set_level_setting(guild_id: int, key: str, value) -> None:
    ALLOWED = {"enabled","xp_min","xp_max","xp_cooldown","level_up_channel","level_up_msg","no_xp_channels","no_xp_roles"}
    if key not in ALLOWED: raise ValueError(f"Bad key: {key}")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO level_settings (guild_id) VALUES (?)", (guild_id,))
        await db.execute(f"UPDATE level_settings SET {key}=? WHERE guild_id=?", (value, guild_id))
        await db.commit()

async def get_user_level(guild_id: int, user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("INSERT OR IGNORE INTO levels (guild_id,user_id) VALUES (?,?)", (guild_id, user_id))
        await db.commit()
        async with db.execute("SELECT * FROM levels WHERE guild_id=? AND user_id=?", (guild_id, user_id)) as c:
            return dict(await c.fetchone())

async def add_xp(guild_id: int, user_id: int, xp: int) -> dict:
    """Add XP. Returns dict with old_level, new_level, new_xp, leveled_up."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("INSERT OR IGNORE INTO levels (guild_id,user_id) VALUES (?,?)", (guild_id, user_id))
        async with db.execute("SELECT xp,level FROM levels WHERE guild_id=? AND user_id=?", (guild_id, user_id)) as c:
            row = await c.fetchone()
        old_xp, old_level = row[0], row[1]
        new_xp = old_xp + xp

        # XP formula: level N requires 5*(N^2) + 50*N + 100 XP total
        def xp_for_level(n): return 5*(n**2) + 50*n + 100
        new_level = old_level
        while new_xp >= xp_for_level(new_level + 1):
            new_xp -= xp_for_level(new_level + 1)
            new_level += 1

        await db.execute(
            "UPDATE levels SET xp=?,level=?,messages=messages+1,last_xp=datetime('now') WHERE guild_id=? AND user_id=?",
            (new_xp, new_level, guild_id, user_id)
        )
        await db.commit()
        return {"old_level": old_level, "new_level": new_level, "new_xp": new_xp,
                "leveled_up": new_level > old_level, "xp_needed": xp_for_level(new_level + 1)}

async def get_level_leaderboard(guild_id: int, limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT user_id,xp,level,messages FROM levels WHERE guild_id=? ORDER BY level DESC,xp DESC LIMIT ?",
            (guild_id, limit)
        ) as c:
            return [dict(r) for r in await c.fetchall()]

async def get_user_rank(guild_id: int, user_id: int) -> int:
    """Returns the 1-based rank of the user in the guild (1 = highest XP)."""
    # Fetch user data first, then open a single DB connection for the count query.
    data = await get_user_level(guild_id, user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*)+1 as r FROM levels WHERE guild_id=? AND (level>? OR (level=? AND xp>?))",
            (guild_id, data["level"], data["level"], data["xp"])
        ) as c:
            return (await c.fetchone())[0]

async def get_level_roles(guild_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM level_roles WHERE guild_id=? ORDER BY level ASC",
            (guild_id,)
        ) as c:
            return [dict(r) for r in await c.fetchall()]

async def set_level_role(guild_id: int, level: int, role_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO level_roles (guild_id,level,role_id) VALUES (?,?,?)",
            (guild_id, level, role_id)
        )
        await db.commit()

async def remove_level_role(guild_id: int, level: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM level_roles WHERE guild_id=? AND level=?", (guild_id, level))
        await db.commit()


# ═══════════════════════════════════════════════════════════════
#  AUTO-MOD  DB FUNCTIONS
# ═══════════════════════════════════════════════════════════════

async def get_automod_settings(guild_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("INSERT OR IGNORE INTO automod_settings (guild_id) VALUES (?)", (guild_id,))
        await db.commit()
        async with db.execute("SELECT * FROM automod_settings WHERE guild_id=?", (guild_id,)) as c:
            return dict(await c.fetchone())

async def set_automod_setting(guild_id: int, key: str, value) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO automod_settings (guild_id) VALUES (?)", (guild_id,))
        await db.execute(f"UPDATE automod_settings SET {key}=? WHERE guild_id=?", (value, guild_id))
        await db.commit()

async def log_automod(guild_id: int, user_id: int, rule: str, action: str, detail: str = "") -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO automod_log (guild_id,user_id,rule,action,detail) VALUES (?,?,?,?,?)",
            (guild_id, user_id, rule, action, detail)
        )
        await db.commit()

async def get_automod_log(guild_id: int, limit: int = 50, offset: int = 0) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM automod_log WHERE guild_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (guild_id, limit, offset)
        ) as c:
            return [dict(r) for r in await c.fetchall()]


# ═══════════════════════════════════════════════════════════════
#  TEMP ROOMS
# ═══════════════════════════════════════════════════════════════

async def get_temproom_settings(guild_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("INSERT OR IGNORE INTO temproom_settings (guild_id) VALUES (?)", (guild_id,))
        await db.commit()
        async with db.execute("SELECT * FROM temproom_settings WHERE guild_id=?", (guild_id,)) as c:
            return dict(await c.fetchone())

async def set_temproom_setting(guild_id: int, key: str, value) -> None:
    ALLOWED = {"enabled","join_channel","category_id","name_template","default_limit","default_bitrate","log_channel"}
    if key not in ALLOWED: raise ValueError(f"Bad key: {key}")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO temproom_settings (guild_id) VALUES (?)", (guild_id,))
        await db.execute(f"UPDATE temproom_settings SET {key}=? WHERE guild_id=?", (value, guild_id))
        await db.commit()

async def create_temp_room(guild_id: int, channel_id: int, owner_id: int, name: str, limit: int = 0) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO temp_rooms (channel_id,guild_id,owner_id,name,user_limit) VALUES (?,?,?,?,?)",
            (channel_id, guild_id, owner_id, name, limit)
        )
        await db.commit()

async def get_temp_room(channel_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM temp_rooms WHERE channel_id=?", (channel_id,)) as c:
            row = await c.fetchone()
            return dict(row) if row else None

async def update_temp_room(channel_id: int, **kwargs) -> None:
    ALLOWED = {"owner_id","name","locked","user_limit","banned_users"}
    sets = ", ".join(f"{k}=?" for k in kwargs if k in ALLOWED)
    vals = [v for k, v in kwargs.items() if k in ALLOWED] + [channel_id]
    if not sets: return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE temp_rooms SET {sets} WHERE channel_id=?", vals)
        await db.commit()

async def delete_temp_room(channel_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM temp_rooms WHERE channel_id=?", (channel_id,))
        await db.commit()

async def get_guild_temp_rooms(guild_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM temp_rooms WHERE guild_id=? ORDER BY created_at DESC", (guild_id,)) as c:
            return [dict(r) for r in await c.fetchall()]

async def get_user_temp_room(guild_id: int, owner_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM temp_rooms WHERE guild_id=? AND owner_id=?", (guild_id, owner_id)) as c:
            row = await c.fetchone()
            return dict(row) if row else None


# ═══════════════════════════════════════════════════════════════
#  SUGGESTIONS
# ═══════════════════════════════════════════════════════════════

async def get_suggestion_settings(guild_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("INSERT OR IGNORE INTO suggestion_settings (guild_id) VALUES (?)", (guild_id,))
        await db.commit()
        async with db.execute("SELECT * FROM suggestion_settings WHERE guild_id=?", (guild_id,)) as c:
            return dict(await c.fetchone())

async def set_suggestion_setting(guild_id: int, key: str, value) -> None:
    ALLOWED = {"channel_id","results_channel","dm_on_decision"}
    if key not in ALLOWED: raise ValueError(f"Bad key: {key}")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO suggestion_settings (guild_id) VALUES (?)", (guild_id,))
        await db.execute(f"UPDATE suggestion_settings SET {key}=? WHERE guild_id=?", (value, guild_id))
        await db.commit()

async def create_suggestion(guild_id: int, channel_id: int, author_id: int, content: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO suggestions (guild_id,channel_id,author_id,content) VALUES (?,?,?,?)",
            (guild_id, channel_id, author_id, content)
        )
        await db.commit()
        return cur.lastrowid

async def set_suggestion_message(suggestion_id: int, message_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE suggestions SET message_id=? WHERE id=?", (message_id, suggestion_id))
        await db.commit()

async def get_suggestion(suggestion_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM suggestions WHERE id=?", (suggestion_id,)) as c:
            row = await c.fetchone()
            return dict(row) if row else None

async def get_suggestion_by_message(message_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM suggestions WHERE message_id=?", (message_id,)) as c:
            row = await c.fetchone()
            return dict(row) if row else None

async def update_suggestion_votes(suggestion_id: int, yes: int, no: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE suggestions SET yes_votes=?, no_votes=? WHERE id=?", (yes, no, suggestion_id))
        await db.commit()

async def decide_suggestion(suggestion_id: int, status: str, mod_id: int, note: str = "") -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE suggestions SET status=?, mod_id=?, mod_note=? WHERE id=?",
            (status, mod_id, note, suggestion_id)
        )
        await db.commit()

async def get_guild_suggestions(guild_id: int, status: str = None, limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if status:
            async with db.execute(
                "SELECT * FROM suggestions WHERE guild_id=? AND status=? ORDER BY created_at DESC LIMIT ?",
                (guild_id, status, limit)
            ) as c:
                return [dict(r) for r in await c.fetchall()]
        async with db.execute(
            "SELECT * FROM suggestions WHERE guild_id=? ORDER BY created_at DESC LIMIT ?",
            (guild_id, limit)
        ) as c:
            return [dict(r) for r in await c.fetchall()]
