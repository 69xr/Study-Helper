# 🤖 Discord Bot + Dashboard

## File Structure

```
discord_bot/
├── main.py              ← Bot entry point
├── config.py            ← ALL settings (token, OAuth, owner ID, etc.)
├── requirements.txt
│
├── utils/
│   ├── db.py            ← Async SQLite layer
│   └── helpers.py       ← Shared embed builders
│
├── cogs/
│   ├── general.py       ← /ping /avatar /uptime /botinfo /help
│   ├── info.py          ← /server /userinfo /roles
│   ├── roles.py         ← /setuprole /panels /deletepanel
│   ├── moderation.py    ← /kick /ban /unban /clear /warn /warnings /clearwarns /delwarn
│   ├── settings.py      ← /setlog /setwelcome /settings
│   └── owner.py         ← /blacklist /reload /shutdown /announce /botstats /dm
│
├── dashboard/
│   ├── app.py           ← Flask web dashboard
│   └── templates/
│       ├── base.html
│       ├── landing.html
│       ├── servers.html
│       ├── dashboard.html
│       ├── settings.html
│       ├── moderation.html
│       ├── roles.html
│       ├── blacklist.html
│       └── analytics.html
│
└── data/
    └── bot.db           ← Shared SQLite (bot + dashboard both use this)
```

---

## Setup

### 1 — Install
```
pip install -r requirements.txt
```

### 2 — Discord Developer Portal
1. Go to https://discord.com/developers/applications
2. Open your app → copy **Application ID** → paste as `CLIENT_ID`
3. OAuth2 tab → copy **Client Secret** → paste as `CLIENT_SECRET`
4. OAuth2 → Redirects → Add: `http://localhost:5000/callback`
5. Bot tab → copy **Token** → paste as `TOKEN`

### 3 — config.py
```python
TOKEN              = "your-bot-token"
OWNER_ID           = 123456789
CLIENT_ID          = "your-client-id"
CLIENT_SECRET      = "your-client-secret"
OAUTH_REDIRECT_URI = "http://localhost:5000/callback"
DASHBOARD_SECRET_KEY = "any-random-string-here"
```

### 4 — Run both
```bash
# Terminal 1
python main.py

# Terminal 2
python dashboard/app.py
```

Open: http://localhost:5000

---

## Dashboard Pages

| Page | Description |
|---|---|
| `/` | Landing — login with Discord |
| `/servers` | Pick server to manage |
| `/dashboard/<id>` | Overview: stats, recent warns, top commands |
| `/dashboard/<id>/settings` | Log channel, welcome channel/message — **auto-saves** |
| `/dashboard/<id>/moderation` | All warnings, delete single or clear by user |
| `/dashboard/<id>/roles` | View & delete self-role panels |
| `/dashboard/<id>/blacklist` | Add/remove blacklisted users (owner only for edits) |
| `/dashboard/<id>/analytics` | Line chart + bar chart of command usage |

---

## How Bot + Dashboard Share Data

```
Discord Bot ──writes──▶ data/bot.db ◀──reads/writes── Flask Dashboard
```

Both processes share the same SQLite file. Changes made in the dashboard
(e.g. setting a log channel) are immediately visible to the bot on its
next interaction, since the bot queries the DB fresh on every command.
"# Sys-Severus-DashBoard" 
