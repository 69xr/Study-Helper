"""
utils/ipc.py — Bot ↔ Dashboard IPC Bridge
==========================================
File-based queue. No Redis or subprocess pipes needed.

  Bot  → writes data/ipc/bot_events.jsonl   (logs emitted to dashboard)
  Dash → writes data/ipc/bot_commands.jsonl  (commands sent to bot)
  Bot  → writes data/ipc/bot_responses.jsonl (ACK/result of each command)
"""

import json, os, time, pathlib
from datetime import datetime, timezone
from config import DATA_DIR

IPC_DIR       = pathlib.Path(DATA_DIR) / "ipc"
BOT_TO_DASH   = IPC_DIR / "bot_events.jsonl"
DASH_TO_BOT   = IPC_DIR / "bot_commands.jsonl"
BOT_RESPONSES = IPC_DIR / "bot_responses.jsonl"  # NEW: ACK channel
MAX_LOG_LINES = 2000
MAX_CMD_AGE   = 30  # seconds


def _ensure_dir():
    IPC_DIR.mkdir(parents=True, exist_ok=True)
    for p in (BOT_TO_DASH, DASH_TO_BOT, BOT_RESPONSES):
        if not p.exists():
            p.touch()


# ══════════════════════════════════════════════════════════════
#  BOT SIDE
# ══════════════════════════════════════════════════════════════

def bot_emit(level: str, message: str, guild_id: int = None, extra: dict = None):
    """Write a log event from the bot process."""
    _ensure_dir()
    entry = {
        "ts":       datetime.now(timezone.utc).strftime("%H:%M:%S"),
        "level":    level.upper(),
        "msg":      message,
        "guild_id": str(guild_id) if guild_id else None,
        "extra":    extra or {},
    }
    with open(BOT_TO_DASH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    # Rotate
    with open(BOT_TO_DASH, "r", encoding="utf-8") as f:
        lines = f.readlines()
    if len(lines) > MAX_LOG_LINES:
        with open(BOT_TO_DASH, "w", encoding="utf-8") as f:
            f.writelines(lines[-MAX_LOG_LINES:])


def bot_ack(cmd_id: str, success: bool, message: str, data: dict = None):
    """Write a command ACK so the dashboard can confirm execution."""
    _ensure_dir()
    entry = {
        "cmd_id":  cmd_id,
        "ok":      success,
        "msg":     message,
        "data":    data or {},
        "ts":      time.time(),
    }
    with open(BOT_RESPONSES, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    # Keep last 500 responses
    with open(BOT_RESPONSES, "r", encoding="utf-8") as f:
        lines = f.readlines()
    if len(lines) > 500:
        with open(BOT_RESPONSES, "w", encoding="utf-8") as f:
            f.writelines(lines[-500:])


def bot_read_commands() -> list[dict]:
    """Read and clear the command queue. Returns only fresh commands."""
    _ensure_dir()
    now = time.time()
    pending = []
    try:
        with open(DASH_TO_BOT, "r", encoding="utf-8") as f:
            lines = f.readlines()
        with open(DASH_TO_BOT, "w", encoding="utf-8") as f:
            pass  # clear immediately
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                cmd = json.loads(line)
                age = now - cmd.get("sent_at", 0)
                if age <= MAX_CMD_AGE:
                    pending.append(cmd)
            except Exception:
                pass
    except Exception:
        pass
    return pending


# ══════════════════════════════════════════════════════════════
#  DASHBOARD SIDE
# ══════════════════════════════════════════════════════════════

def dash_read_events(since_line: int = 0) -> tuple[list[dict], int]:
    """Return new log events since the given line offset."""
    _ensure_dir()
    try:
        with open(BOT_TO_DASH, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
        events = []
        for line in all_lines[since_line:]:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except Exception:
                    pass
        return events, len(all_lines)
    except Exception:
        return [], since_line


def dash_send_command(action: str, params: dict = None, cmd_id: str = None) -> str:
    """
    Write a command to the bot queue.
    Returns the cmd_id so the caller can poll for ACK.
    """
    _ensure_dir()
    import uuid
    cid = cmd_id or str(uuid.uuid4())[:8]
    cmd = {
        "cmd_id":  cid,
        "action":  action,
        "params":  params or {},
        "sent_at": time.time(),
        "sent_ts": datetime.now(timezone.utc).isoformat(),
    }
    try:
        with open(DASH_TO_BOT, "a", encoding="utf-8") as f:
            f.write(json.dumps(cmd) + "\n")
        return cid
    except Exception:
        return ""


def dash_poll_ack(cmd_id: str, max_wait: float = 8.0) -> dict:
    """
    Poll BOT_RESPONSES for an ACK matching cmd_id.
    Blocks up to max_wait seconds. Returns the ACK dict or error.
    """
    _ensure_dir()
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            with open(BOT_RESPONSES, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("cmd_id") == cmd_id:
                        # Remove from file
                        with open(BOT_RESPONSES, "w", encoding="utf-8") as fw:
                            fw.writelines(
                                l for l in lines
                                if cmd_id not in l
                            )
                        return entry
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(0.25)
    return {"cmd_id": cmd_id, "ok": False, "msg": "Timeout — bot did not respond in 8s. Is the bot running?"}


def dash_get_recent_logs(n: int = 100) -> list[dict]:
    events, _ = dash_read_events(0)
    return events[-n:]


# ══════════════════════════════════════════════════════════════
#  MODULE STATE  (persisted as JSON for dashboard reads)
# ══════════════════════════════════════════════════════════════

MODULE_STATE_FILE = IPC_DIR / "module_state.json"

def read_module_state() -> dict:
    _ensure_dir()
    try:
        with open(MODULE_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def write_module_state(state: dict) -> None:
    _ensure_dir()
    with open(MODULE_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
