"""
utils/db.py  —  Async SQLite database manager
All DB access goes through this module. Each method opens its own
connection so there are no cross-thread/cross-task issues.
"""
import aiosqlite
import asyncio
from config import DB_PATH


# ═══════════════════════════════════════════════════════════════
#  SCHEMA  (core tables — always created on first run)
# ═══════════════════════════════════════════════════════════════

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id          INTEGER PRIMARY KEY,
    log_channel       INTEGER DEFAULT NULL,
    welcome_channel   INTEGER DEFAULT NULL,
    welcome_msg       TEXT    DEFAULT 'Welcome {user} to **{server}**!',
    mute_role         INTEGER DEFAULT NULL,
    verify_role       INTEGER DEFAULT NULL,
    unverified_role   INTEGER DEFAULT NULL,
    anti_raid         INTEGER DEFAULT 0,
    raid_threshold    INTEGER DEFAULT 10,
    min_account_age   INTEGER DEFAULT 0,
    bot_status        TEXT    DEFAULT NULL,
    bot_status_type   TEXT    DEFAULT 'watching',
    log_msg_delete    INTEGER DEFAULT NULL,
    log_msg_edit      INTEGER DEFAULT NULL,
    log_member_join   INTEGER DEFAULT NULL,
    log_member_leave  INTEGER DEFAULT NULL,
    log_member_update INTEGER DEFAULT NULL,
    log_voice         INTEGER DEFAULT NULL,
    log_mod_actions   INTEGER DEFAULT NULL,
    log_roles         INTEGER DEFAULT NULL,
    auto_roles        TEXT    DEFAULT '[]',
    dj_role           INTEGER DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS warnings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    mod_id     INTEGER NOT NULL,
    reason     TEXT    NOT NULL,
    created_at TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_warn_guild_user ON warnings(guild_id, user_id);

CREATE TABLE IF NOT EXISTS warn_thresholds (
    guild_id   INTEGER NOT NULL,
    count      INTEGER NOT NULL,
    action     TEXT    NOT NULL,  -- mute | kick | ban
    duration   INTEGER DEFAULT NULL,  -- seconds (for mute), NULL = permanent
    PRIMARY KEY (guild_id, count)
);

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

CREATE TABLE IF NOT EXISTS role_panel_entries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    panel_id   INTEGER NOT NULL REFERENCES role_panels(id) ON DELETE CASCADE,
    role_id    INTEGER NOT NULL,
    label      TEXT    DEFAULT 'Role',
    emoji      TEXT    DEFAULT NULL,
    style      INTEGER DEFAULT 1,
    position   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS blacklist (
    user_id    INTEGER PRIMARY KEY,
    reason     TEXT    NOT NULL,
    added_by   INTEGER NOT NULL,
    added_at   TEXT    DEFAULT (datetime('now'))
);

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

CREATE TABLE IF NOT EXISTS command_stats (
    command    TEXT    NOT NULL,
    guild_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    used_at    TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_cmd_guild ON command_stats(guild_id, used_at);
"""


# ═══════════════════════════════════════════════════════════════
#  EXTENDED SCHEMA  (feature tables)
# ═══════════════════════════════════════════════════════════════

NEW_TABLES = """
PRAGMA journal_mode=WAL;

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
    status      TEXT    DEFAULT 'open',
    claimed_by  INTEGER DEFAULT NULL,
    transcript  TEXT    DEFAULT NULL,
    opened_at   TEXT    DEFAULT (datetime('now')),
    closed_at   TEXT    DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_tickets_guild  ON tickets(guild_id);
CREATE INDEX IF NOT EXISTS idx_tickets_user   ON tickets(user_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);

CREATE TABLE IF NOT EXISTS economy (
    guild_id     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    balance      INTEGER DEFAULT 0,
    bank         INTEGER DEFAULT 0,
    total_earned INTEGER DEFAULT 0,
    last_daily   TEXT    DEFAULT NULL,
    last_work    TEXT    DEFAULT NULL,
    PRIMARY KEY (guild_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_econ_guild ON economy(guild_id, balance DESC);

CREATE TABLE IF NOT EXISTS levels (
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    xp          INTEGER DEFAULT 0,
    level       INTEGER DEFAULT 0,
    messages    INTEGER DEFAULT 0,
    last_xp     TEXT    DEFAULT NULL,
    PRIMARY KEY (guild_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_lvl_guild ON levels(guild_id, xp DESC);

CREATE TABLE IF NOT EXISTS automod_settings (
    guild_id            INTEGER PRIMARY KEY,
    enabled             INTEGER DEFAULT 0,
    spam_enabled        INTEGER DEFAULT 0,
    spam_threshold      INTEGER DEFAULT 5,
    spam_window         INTEGER DEFAULT 5,
    spam_action         TEXT    DEFAULT 'mute',
    links_enabled       INTEGER DEFAULT 0,
    links_whitelist     TEXT    DEFAULT '[]',
    links_action        TEXT    DEFAULT 'delete',
    words_enabled       INTEGER DEFAULT 0,
    bad_words           TEXT    DEFAULT '[]',
    words_action        TEXT    DEFAULT 'delete',
    caps_enabled        INTEGER DEFAULT 0,
    caps_threshold      INTEGER DEFAULT 70,
    caps_min_length     INTEGER DEFAULT 10,
    caps_action         TEXT    DEFAULT 'delete',
    mention_enabled     INTEGER DEFAULT 0,
    mention_threshold   INTEGER DEFAULT 5,
    mention_action      TEXT    DEFAULT 'mute',
    exempt_roles        TEXT    DEFAULT '[]',
    exempt_channels     TEXT    DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS automod_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    rule        TEXT    NOT NULL,
    action      TEXT    NOT NULL,
    detail      TEXT    DEFAULT '',
    created_at  TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_aml_guild ON automod_log(guild_id);

CREATE TABLE IF NOT EXISTS command_aliases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    alias       TEXT    NOT NULL,
    command     TEXT    NOT NULL,
    created_at  TEXT    DEFAULT (datetime('now')),
    UNIQUE(guild_id, alias)
);
CREATE INDEX IF NOT EXISTS idx_alias_guild ON command_aliases(guild_id);

CREATE TABLE IF NOT EXISTS mod_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    mod_id      INTEGER NOT NULL,
    note        TEXT    NOT NULL,
    created_at  TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_notes_guild_user ON mod_notes(guild_id, user_id);

CREATE TABLE IF NOT EXISTS custom_commands (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    trigger     TEXT    NOT NULL,
    response    TEXT    NOT NULL,
    embed       INTEGER DEFAULT 0,
    embed_color TEXT    DEFAULT '#5865F2',
    embed_title TEXT    DEFAULT '',
    uses        INTEGER DEFAULT 0,
    created_by  INTEGER NOT NULL,
    created_at  TEXT    DEFAULT (datetime('now')),
    UNIQUE(guild_id, trigger)
);
CREATE INDEX IF NOT EXISTS idx_cc_guild ON custom_commands(guild_id);

CREATE TABLE IF NOT EXISTS temproom_settings (
    guild_id        INTEGER PRIMARY KEY,
    enabled         INTEGER DEFAULT 0,
    join_channel    INTEGER DEFAULT NULL,
    category_id     INTEGER DEFAULT NULL,
    name_template   TEXT    DEFAULT '{user}''s Room',
    default_limit   INTEGER DEFAULT 0,
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
    banned_users    TEXT    DEFAULT '[]',
    created_at      TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tr_guild ON temp_rooms(guild_id);

CREATE TABLE IF NOT EXISTS reminders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    channel_id  INTEGER NOT NULL,
    guild_id    INTEGER,
    content     TEXT    NOT NULL,
    remind_at   TEXT    NOT NULL,  -- ISO datetime UTC
    created_at  TEXT    DEFAULT (datetime('now')),
    done        INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(remind_at, done);

CREATE TABLE IF NOT EXISTS afk_users (
    guild_id        INTEGER NOT NULL,
    user_id         INTEGER NOT NULL,
    reason          TEXT    NOT NULL DEFAULT 'AFK',
    original_nick   TEXT    DEFAULT NULL,
    afk_since       TEXT    DEFAULT (datetime('now')),
    PRIMARY KEY (guild_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_afk_guild ON afk_users(guild_id);
"""


# ═══════════════════════════════════════════════════════════════
#  INIT
# ═══════════════════════════════════════════════════════════════

async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def init_new_tables() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(NEW_TABLES)
        await db.commit()

    # Column migrations for pre-existing databases
    _migrations = [
        "ALTER TABLE guild_settings ADD COLUMN auto_roles TEXT DEFAULT '[]'",
        "ALTER TABLE guild_settings ADD COLUMN dj_role INTEGER DEFAULT NULL",
        "ALTER TABLE guild_settings ADD COLUMN log_msg_delete INTEGER DEFAULT NULL",
        "ALTER TABLE guild_settings ADD COLUMN log_msg_edit INTEGER DEFAULT NULL",
        "ALTER TABLE guild_settings ADD COLUMN log_member_join INTEGER DEFAULT NULL",
        "ALTER TABLE guild_settings ADD COLUMN log_member_leave INTEGER DEFAULT NULL",
        "ALTER TABLE guild_settings ADD COLUMN log_member_update INTEGER DEFAULT NULL",
        "ALTER TABLE guild_settings ADD COLUMN log_voice INTEGER DEFAULT NULL",
        "ALTER TABLE guild_settings ADD COLUMN log_mod_actions INTEGER DEFAULT NULL",
        "ALTER TABLE guild_settings ADD COLUMN log_roles INTEGER DEFAULT NULL",
        "ALTER TABLE guild_settings ADD COLUMN anti_raid INTEGER DEFAULT 0",
        "ALTER TABLE guild_settings ADD COLUMN raid_threshold INTEGER DEFAULT 10",
        "ALTER TABLE guild_settings ADD COLUMN min_account_age INTEGER DEFAULT 0",
        "ALTER TABLE guild_settings ADD COLUMN verify_role INTEGER DEFAULT NULL",
        "ALTER TABLE guild_settings ADD COLUMN unverified_role INTEGER DEFAULT NULL",
        "ALTER TABLE guild_settings ADD COLUMN bot_status TEXT DEFAULT NULL",
        "ALTER TABLE guild_settings ADD COLUMN bot_status_type TEXT DEFAULT 'watching'",
        "ALTER TABLE audit_log ADD COLUMN extra TEXT DEFAULT NULL",
        "ALTER TABLE role_panel_entries ADD COLUMN label TEXT DEFAULT 'Role'",
        "ALTER TABLE role_panel_entries ADD COLUMN position INTEGER DEFAULT 0",
    ]
    async with aiosqlite.connect(DB_PATH) as db:
        for stmt in _migrations:
            try:
                await db.execute(stmt)
                await db.commit()
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════
#  GUILD SETTINGS
# ═══════════════════════════════════════════════════════════════

async def ensure_guild(guild_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (guild_id,))
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
    ALLOWED = {
        "log_channel", "welcome_channel", "welcome_msg", "mute_role",
        "verify_role", "unverified_role",
        "anti_raid", "raid_threshold", "min_account_age",
        "bot_status", "bot_status_type",
        "log_msg_delete", "log_msg_edit", "log_member_join", "log_member_leave",
        "log_member_update", "log_voice", "log_mod_actions", "log_roles",
        "auto_roles", "dj_role",
    }
    if key not in ALLOWED:
        raise ValueError(f"Unknown setting: {key}")
    await ensure_guild(guild_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE guild_settings SET {key} = ? WHERE guild_id = ?", (value, guild_id))
        await db.commit()


# ═══════════════════════════════════════════════════════════════
#  WARNINGS
# ═══════════════════════════════════════════════════════════════

async def add_warning(guild_id: int, user_id: int, mod_id: int, reason: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO warnings (guild_id, user_id, mod_id, reason) VALUES (?,?,?,?)",
            (guild_id, user_id, mod_id, reason))
        await db.commit()
        async with db.execute(
            "SELECT COUNT(*) FROM warnings WHERE guild_id=? AND user_id=?",
            (guild_id, user_id)
        ) as cur:
            return (await cur.fetchone())[0]


async def get_warnings(guild_id: int, user_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM warnings WHERE guild_id=? AND user_id=? ORDER BY created_at DESC",
            (guild_id, user_id)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def clear_warnings(guild_id: int, user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM warnings WHERE guild_id=? AND user_id=?",
            (guild_id, user_id)
        ) as cur:
            count = (await cur.fetchone())[0]
        await db.execute(
            "DELETE FROM warnings WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        await db.commit()
        return count


async def remove_warning(warning_id: int, guild_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM warnings WHERE id=? AND guild_id=?", (warning_id, guild_id)
        ) as cur:
            if not await cur.fetchone():
                return False
        await db.execute("DELETE FROM warnings WHERE id=?", (warning_id,))
        await db.commit()
        return True


# ═══════════════════════════════════════════════════════════════
#  WARN THRESHOLDS
# ═══════════════════════════════════════════════════════════════

async def get_warn_thresholds(guild_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM warn_thresholds WHERE guild_id=? ORDER BY count ASC", (guild_id,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def set_warn_threshold(guild_id: int, count: int, action: str, duration: int | None = None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO warn_thresholds (guild_id, count, action, duration) VALUES (?,?,?,?)",
            (guild_id, count, action, duration))
        await db.commit()


async def delete_warn_threshold(guild_id: int, count: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM warn_thresholds WHERE guild_id=? AND count=?", (guild_id, count))
        await db.commit()


async def get_threshold_for_count(guild_id: int, count: int) -> dict | None:
    """Return the threshold that exactly matches this warn count, if any."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM warn_thresholds WHERE guild_id=? AND count=?", (guild_id, count)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


# ═══════════════════════════════════════════════════════════════
#  ROLE PANELS
# ═══════════════════════════════════════════════════════════════

async def save_role_panel(
    guild_id: int, channel_id: int, message_id: int,
    title: str, description: str, color: int, created_by: int,
    role_entries: list[dict]
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO role_panels
               (guild_id, channel_id, message_id, title, description, color, created_by)
               VALUES (?,?,?,?,?,?,?)""",
            (guild_id, channel_id, message_id, title, description, color, created_by))
        panel_id = cur.lastrowid
        for entry in role_entries:
            await db.execute(
                "INSERT INTO role_panel_entries (panel_id, role_id, label, emoji, style) VALUES (?,?,?,?,?)",
                (panel_id, entry["role_id"], entry.get("label", "Role"),
                 entry.get("emoji"), entry.get("style", 1)))
        await db.commit()
        return panel_id


async def get_all_role_panels(guild_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM role_panels WHERE guild_id=? ORDER BY created_at DESC", (guild_id,)
        ) as cur:
            panels = [dict(r) for r in await cur.fetchall()]
        for panel in panels:
            async with db.execute(
                "SELECT * FROM role_panel_entries WHERE panel_id=? ORDER BY position ASC",
                (panel["id"],)
            ) as cur:
                panel["entries"] = [dict(r) for r in await cur.fetchall()]
        return panels


async def delete_role_panel(panel_id: int, guild_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM role_panels WHERE id=? AND guild_id=?", (panel_id, guild_id)
        ) as cur:
            if not await cur.fetchone():
                return False
        await db.execute("DELETE FROM role_panel_entries WHERE panel_id=?", (panel_id,))
        await db.execute("DELETE FROM role_panels WHERE id=?", (panel_id,))
        await db.commit()
        return True


async def get_all_panels_for_restore() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM role_panels") as cur:
            panels = [dict(r) for r in await cur.fetchall()]
        for panel in panels:
            async with db.execute(
                "SELECT * FROM role_panel_entries WHERE panel_id=? ORDER BY position ASC",
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
            (user_id, reason, added_by))
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
#  COMMAND STATS
# ═══════════════════════════════════════════════════════════════

async def log_command(command: str, guild_id: int, user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO command_stats (command, guild_id, user_id) VALUES (?,?,?)",
            (command, guild_id, user_id))
        await db.commit()


async def get_top_commands(limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT command, COUNT(*) as uses FROM command_stats GROUP BY command ORDER BY uses DESC LIMIT ?",
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
            (guild_id, action, mod_id, target_id, reason, extra))
        await db.commit()


async def get_audit_log(guild_id: int, limit: int = 50, offset: int = 0,
                         action_filter: str = None) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if action_filter:
            async with db.execute(
                "SELECT * FROM audit_log WHERE guild_id=? AND action=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (guild_id, action_filter, limit, offset)
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]
        async with db.execute(
            "SELECT * FROM audit_log WHERE guild_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (guild_id, limit, offset)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_audit_log_count(guild_id: int, action_filter: str = None) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        if action_filter:
            async with db.execute(
                "SELECT COUNT(*) FROM audit_log WHERE guild_id=? AND action=?",
                (guild_id, action_filter)
            ) as cur:
                return (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM audit_log WHERE guild_id=?", (guild_id,)
        ) as cur:
            return (await cur.fetchone())[0]


# ═══════════════════════════════════════════════════════════════
#  COMMAND ALIASES
# ═══════════════════════════════════════════════════════════════

async def get_aliases(guild_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM command_aliases WHERE guild_id=? ORDER BY alias ASC", (guild_id,)
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def set_alias(guild_id: int, alias: str, command: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO command_aliases (guild_id, alias, command) VALUES (?,?,?)",
            (guild_id, alias.lower().strip(), command.lower().strip()))
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
            (guild_id, alias.lower()))
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


# ═══════════════════════════════════════════════════════════════
#  TICKETS
# ═══════════════════════════════════════════════════════════════

async def get_ticket_settings(guild_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("INSERT OR IGNORE INTO ticket_settings (guild_id) VALUES (?)", (guild_id,))
        await db.commit()
        async with db.execute("SELECT * FROM ticket_settings WHERE guild_id=?", (guild_id,)) as c:
            return dict(await c.fetchone())


async def set_ticket_setting(guild_id: int, key: str, value) -> None:
    ALLOWED = {"category_id", "log_channel", "support_role", "ticket_msg", "max_open"}
    if key not in ALLOWED:
        raise ValueError(f"Bad key: {key}")
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
            (guild_id, channel_id, user_id, num, subject))
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
    ALLOWED = {"status", "claimed_by", "transcript", "closed_at", "subject"}
    sets = ", ".join(f"{k}=?" for k in kwargs if k in ALLOWED)
    vals = [v for k, v in kwargs.items() if k in ALLOWED] + [ticket_id]
    if not sets:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE tickets SET {sets} WHERE id=?", vals)
        await db.commit()


async def get_guild_tickets(guild_id: int, status: str = None, limit: int = 50, offset: int = 0) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        q = "SELECT * FROM tickets WHERE guild_id=?"
        p = [guild_id]
        if status:
            q += " AND status=?"
            p.append(status)
        q += " ORDER BY opened_at DESC LIMIT ? OFFSET ?"
        p += [limit, offset]
        async with db.execute(q, p) as c:
            return [dict(r) for r in await c.fetchall()]


# ═══════════════════════════════════════════════════════════════
#  ECONOMY  (read-only queries used by dashboard search)
# ═══════════════════════════════════════════════════════════════

async def get_balance(guild_id: int, user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)", (guild_id, user_id))
        await db.commit()
        async with db.execute("SELECT * FROM economy WHERE guild_id=? AND user_id=?", (guild_id, user_id)) as c:
            return dict(await c.fetchone())


async def get_leaderboard(guild_id: int, limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT user_id, balance, bank, total_earned FROM economy WHERE guild_id=? ORDER BY balance+bank DESC LIMIT ?",
            (guild_id, limit)
        ) as c:
            return [dict(r) for r in await c.fetchall()]


# ═══════════════════════════════════════════════════════════════
#  LEVELS  (read-only queries used by dashboard search)
# ═══════════════════════════════════════════════════════════════

async def get_user_level(guild_id: int, user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("INSERT OR IGNORE INTO levels (guild_id,user_id) VALUES (?,?)", (guild_id, user_id))
        await db.commit()
        async with db.execute("SELECT * FROM levels WHERE guild_id=? AND user_id=?", (guild_id, user_id)) as c:
            return dict(await c.fetchone())


async def get_level_leaderboard(guild_id: int, limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT user_id,xp,level,messages FROM levels WHERE guild_id=? ORDER BY level DESC,xp DESC LIMIT ?",
            (guild_id, limit)
        ) as c:
            return [dict(r) for r in await c.fetchall()]


# ═══════════════════════════════════════════════════════════════
#  AUTOMOD
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
            (guild_id, user_id, rule, action, detail))
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
    ALLOWED = {"enabled", "join_channel", "category_id", "name_template",
               "default_limit", "default_bitrate", "log_channel"}
    if key not in ALLOWED:
        raise ValueError(f"Bad key: {key}")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO temproom_settings (guild_id) VALUES (?)", (guild_id,))
        await db.execute(f"UPDATE temproom_settings SET {key}=? WHERE guild_id=?", (value, guild_id))
        await db.commit()


async def create_temp_room(guild_id: int, channel_id: int, owner_id: int, name: str, limit: int = 0) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO temp_rooms (channel_id,guild_id,owner_id,name,user_limit) VALUES (?,?,?,?,?)",
            (channel_id, guild_id, owner_id, name, limit))
        await db.commit()


async def get_temp_room(channel_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM temp_rooms WHERE channel_id=?", (channel_id,)) as c:
            row = await c.fetchone()
            return dict(row) if row else None


async def update_temp_room(channel_id: int, **kwargs) -> None:
    ALLOWED = {"owner_id", "name", "locked", "user_limit", "banned_users"}
    sets = ", ".join(f"{k}=?" for k in kwargs if k in ALLOWED)
    vals = [v for k, v in kwargs.items() if k in ALLOWED] + [channel_id]
    if not sets:
        return
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
        async with db.execute(
            "SELECT * FROM temp_rooms WHERE guild_id=? ORDER BY created_at DESC", (guild_id,)
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_user_temp_room(guild_id: int, owner_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM temp_rooms WHERE guild_id=? AND owner_id=?", (guild_id, owner_id)
        ) as c:
            row = await c.fetchone()
            return dict(row) if row else None


# ═══════════════════════════════════════════════════════════════
#  MOD NOTES
# ═══════════════════════════════════════════════════════════════

async def add_mod_note(guild_id: int, user_id: int, mod_id: int, note: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO mod_notes (guild_id,user_id,mod_id,note) VALUES (?,?,?,?)",
            (guild_id, user_id, mod_id, note))
        await db.commit()
        return cur.lastrowid


async def get_mod_notes(guild_id: int, user_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM mod_notes WHERE guild_id=? AND user_id=? ORDER BY created_at DESC",
            (guild_id, user_id)
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def delete_mod_note(note_id: int, guild_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM mod_notes WHERE id=? AND guild_id=?", (note_id, guild_id))
        await db.commit()
        return cur.rowcount > 0


# ═══════════════════════════════════════════════════════════════
#  CUSTOM COMMANDS
# ═══════════════════════════════════════════════════════════════

async def get_custom_commands(guild_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM custom_commands WHERE guild_id=? ORDER BY trigger", (guild_id,)
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_custom_command(guild_id: int, trigger: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM custom_commands WHERE guild_id=? AND trigger=?",
            (guild_id, trigger.lower())
        ) as c:
            row = await c.fetchone()
            return dict(row) if row else None


async def create_custom_command(guild_id: int, trigger: str, response: str,
                                 embed: int, color: str, title: str, mod_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT OR REPLACE INTO custom_commands "
            "(guild_id,trigger,response,embed,embed_color,embed_title,created_by) VALUES (?,?,?,?,?,?,?)",
            (guild_id, trigger.lower(), response, embed, color, title, mod_id))
        await db.commit()
        return cur.lastrowid


async def delete_custom_command(guild_id: int, trigger: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM custom_commands WHERE guild_id=? AND trigger=?",
            (guild_id, trigger.lower()))
        await db.commit()
        return cur.rowcount > 0


async def increment_command_uses(guild_id: int, trigger: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE custom_commands SET uses=uses+1 WHERE guild_id=? AND trigger=?",
            (guild_id, trigger.lower()))
        await db.commit()


# ═══════════════════════════════════════════════════════════════
#  AUTO-ROLES
# ═══════════════════════════════════════════════════════════════

async def get_auto_roles(guild_id: int) -> list[int]:
    import json
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT auto_roles FROM guild_settings WHERE guild_id=?", (guild_id,)
        ) as c:
            row = await c.fetchone()
            if not row or not row[0]:
                return []
            try:
                return json.loads(row[0])
            except Exception:
                return []


async def set_auto_roles(guild_id: int, role_ids: list[int]) -> None:
    import json
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (guild_id,))
        await db.execute("UPDATE guild_settings SET auto_roles=? WHERE guild_id=?",
                         (json.dumps(role_ids), guild_id))
        await db.commit()


# ═══════════════════════════════════════════════════════════════
#  REMINDERS
# ═══════════════════════════════════════════════════════════════

async def create_reminder(user_id: int, channel_id: int, guild_id: int | None,
                           content: str, remind_at: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO reminders (user_id,channel_id,guild_id,content,remind_at) VALUES (?,?,?,?,?)",
            (user_id, channel_id, guild_id, content, remind_at))
        await db.commit()
        return cur.lastrowid


async def get_pending_reminders() -> list[dict]:
    """All reminders due now or in the past that haven't fired yet."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM reminders WHERE done=0 AND remind_at <= datetime('now') ORDER BY remind_at ASC"
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_all_pending_reminders() -> list[dict]:
    """All future reminders — used to rebuild in-memory schedule on restart."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM reminders WHERE done=0 ORDER BY remind_at ASC"
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def mark_reminder_done(reminder_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE reminders SET done=1 WHERE id=?", (reminder_id,))
        await db.commit()


async def get_user_reminders(user_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM reminders WHERE user_id=? AND done=0 ORDER BY remind_at ASC",
            (user_id,)
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def delete_reminder(reminder_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM reminders WHERE id=? AND user_id=? AND done=0",
            (reminder_id, user_id))
        await db.commit()
        return cur.rowcount > 0

# ═══════════════════════════════════════════════════════════════
#  AFK SYSTEM
# ═══════════════════════════════════════════════════════════════

async def set_afk(guild_id: int, user_id: int, reason: str, original_nick: str | None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO afk_users (guild_id, user_id, reason, original_nick, afk_since)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            (guild_id, user_id, reason, original_nick)
        )
        await db.commit()


async def get_afk(guild_id: int, user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM afk_users WHERE guild_id=? AND user_id=?",
            (guild_id, user_id)
        ) as c:
            row = await c.fetchone()
            return dict(row) if row else None


async def remove_afk(guild_id: int, user_id: int) -> dict | None:
    """Remove AFK and return the old record (to restore nickname)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM afk_users WHERE guild_id=? AND user_id=?",
            (guild_id, user_id)
        ) as c:
            row = await c.fetchone()
            record = dict(row) if row else None
        if record:
            await db.execute(
                "DELETE FROM afk_users WHERE guild_id=? AND user_id=?",
                (guild_id, user_id)
            )
            await db.commit()
        return record


async def get_all_afk(guild_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM afk_users WHERE guild_id=? ORDER BY afk_since DESC",
            (guild_id,)
        ) as c:
            return [dict(r) for r in await c.fetchall()]


# ═══════════════════════════════════════════════════════════════
#  ANALYTICS — per-guild
# ═══════════════════════════════════════════════════════════════

async def get_guild_command_stats(guild_id: int, days: int = 30) -> list[dict]:
    """Top commands for a specific guild in the last N days."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT command, COUNT(*) as total
               FROM command_stats
               WHERE guild_id=? AND used_at >= datetime('now', ?)
               GROUP BY command ORDER BY total DESC LIMIT 15""",
            (guild_id, f"-{days} days")
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_guild_command_daily(guild_id: int, days: int = 14) -> list[dict]:
    """Commands per day for the last N days (for chart)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT date(used_at) as day, COUNT(*) as total
               FROM command_stats
               WHERE guild_id=? AND used_at >= datetime('now', ?)
               GROUP BY date(used_at) ORDER BY day ASC""",
            (guild_id, f"-{days} days")
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_guild_command_total(guild_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM command_stats WHERE guild_id=?", (guild_id,)
        ) as c:
            return (await c.fetchone())[0]


async def get_guild_unique_users(guild_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(DISTINCT user_id) FROM command_stats WHERE guild_id=?", (guild_id,)
        ) as c:
            return (await c.fetchone())[0]


async def get_guild_warnings_over_time(guild_id: int, days: int = 14) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT date(created_at) as day, COUNT(*) as total
               FROM warnings WHERE guild_id=? AND created_at >= datetime('now', ?)
               GROUP BY date(created_at) ORDER BY day ASC""",
            (guild_id, f"-{days} days")
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_guild_afk_count(guild_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM afk_users WHERE guild_id=?", (guild_id,)
        ) as c:
            return (await c.fetchone())[0]


# ═══════════════════════════════════════════════════════════════
#  VERIFICATION
# ═══════════════════════════════════════════════════════════════

async def get_verify_settings(guild_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT verify_role, unverified_role FROM guild_settings WHERE guild_id=?", (guild_id,)
        ) as c:
            row = await c.fetchone()
            return dict(row) if row else {}
