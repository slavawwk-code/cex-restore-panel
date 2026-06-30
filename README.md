# Cex Restore Panel

Internal Telegram CRM for managing advertising campaigns using multiple Telegram user accounts.

For the first Ubuntu VPS deployment, use [DEPLOY.md](DEPLOY.md). The repository
includes systemd configuration, safe install/update/control scripts, rotating
production logs, SQLite/session backups, an offline smoke test, and a local
health check.

## Overview

Cex Restore Panel is designed to help manage advertising campaigns across multiple Telegram accounts while complying with Telegram's policies. It provides:

- **Management Bot**: A Telegram bot interface for operators to manage campaigns
- **Advertising Accounts**: Multiple Telegram user accounts that send promotional messages
- **Scheduler**: Automatic message sending with configurable cooldowns
- **DRY RUN Mode**: Test the system without actually sending messages

## Features

- ✅ Multi-account management
- ✅ Template-based messaging
- ✅ Per-chat cooldown configuration
- ✅ Scheduler with deterministic behavior
- ✅ Comprehensive logging and error tracking
- ✅ Role-based access (Owner/Operator)
- ✅ DRY RUN mode for testing
- ✅ Russian operator interface
- ✅ Per-account SOCKS5, SOCKS4, and HTTP proxy configuration
- ✅ Fast proxy checks and full diagnostics through Telegram
- ✅ Background proxy monitoring with state-change alerts
- ✅ Minimal account cards with a 100-point operational health score
- ✅ Per-account proxy check history (latest 20 records)

## Technology Stack

- Python 3.12+
- aiogram 3 (Telegram bot framework)
- Telethon (Telegram user account client)
- SQLite (database)
- asyncio-based internal scheduler
- SQLAlchemy (ORM)
- python-socks (async proxy transport)

## Project Structure

```
cex-restore-panel/
├── app/
│   ├── __init__.py
│   ├── handlers/           # Telegram bot command handlers
│   ├── services/           # Business logic
│   ├── database/           # Database models and utilities
│   ├── scheduler/          # Message scheduling logic
│   ├── telethon/           # Telethon client wrapper
│   ├── keyboards/          # Inline keyboard definitions
│   └── models/             # Pydantic/data models
├── sessions/               # Telethon session files
├── logs/                   # Application logs
├── data/                   # SQLite database
├── main.py                 # Application entry point
├── .env.example            # Environment variables template
├── requirements.txt        # Python dependencies
└── README.md               # This file
```

## Setup Instructions

### 1. Clone and Install Dependencies

```bash
cd cex-restore-panel
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
python -m pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Required configuration:
- `BOT_TOKEN`: Your Telegram bot token (get from BotFather)
- `TELEGRAM_API_ID`: Your Telegram API ID (get from my.telegram.org)
- `TELEGRAM_API_HASH`: Your Telegram API Hash (get from my.telegram.org)
- `OWNER_TELEGRAM_ID`: Your Telegram user ID (get from @userinfobot)
- `PROXY_MONITOR_INTERVAL_SECONDS`: Proxy monitor interval; defaults to `1800`,
  use `0` to disable monitoring

### 3. Initialize Database

```bash
python -c "from app.database.models import init_db; init_db()"
```

### 4. Run the Bot

```bash
python main.py
```

On first startup the application automatically creates `data/`, `sessions/`,
`logs/`, and `backups/`, initializes SQLite, and applies additive migrations.
Run `python scripts/smoke_test.py` before production startup; it performs no
Telegram network requests.

## Usage

### Management Bot

Once running, open Telegram and search for your bot. The interface is entirely keyboard-based:

- **Accounts**: Manage advertising accounts
- **Chats**: Configure target chats and cooldowns
- **Templates**: Create and manage message templates
- **Campaigns**: Control the scheduler
- **Logs**: View message send history and errors
- **Operators**: Manage team members (Owner only)
- **Settings**: Configure DRY RUN, cooldowns, etc.

The operator interface is in Russian. Internal code, database values, and logs
remain in English.

### Proxy health monitoring

Every configured account has two checks. **Быстрая проверка** tests only the
saved proxy type with a short timeout. **Полная диагностика** tests SOCKS5,
HTTP, and SOCKS4 for proxies whose type was detected automatically; proxies
entered with an explicit scheme are tested only with that scheme.

The independent proxy monitor runs every 30 minutes by default. It performs
only fast checks and sends the owner one notification when a working proxy
fails and one notification when it recovers. It does not repeat alerts while
the state remains failed.

### Account health score

The operator UI calculates health from existing operational data without
changing sending behavior: Telegram authorization (20), working proxy (10),
successful latest proxy check (10), running scheduler (15), enabled account
(15), configured active templates (10), active chats (10), and no send errors
in the previous 24 hours (10). The total is 100 points. Scores are displayed
as green at 90–100, yellow at 60–89, and red at 0–59.

Each proxy test adds a credential-free record to `proxy_check_history`.
Only the latest 20 records per account are retained.

### DRY RUN Mode

With `DRY_RUN=True` in `.env`, the bot will:
- Simulate message sending
- Create logs as if messages were sent
- Print actions to console
- NOT actually send any Telegram messages

This is enabled by default for development.

## Advertising Accounts

Adding an advertising account:
1. Open the Management Bot
2. Navigate to **Accounts** → **Add Account**
3. Enter phone number (Telethon will start authentication)
4. Confirm the code sent to Telegram
5. Account is ready to use

### Per-account proxy

Open **Аккаунты → Список аккаунтов → account → Прокси**. Each account can use
its own SOCKS5, SOCKS4, or HTTP proxy. Host and port are required; username and
password are optional. Use **Проверить прокси** before requesting a Telegram
login code. The test connects to Telegram through the configured route.

The default setup accepts a complete proxy in one message: `host:port`,
`host:port:user:password`, `user:password@host:port`, or an `http://`,
`https://`, `socks4://`, or `socks5://` URL. The manual field-by-field wizard
remains available for uncommon inputs. `https://` URLs are normalized to
Telethon's HTTP CONNECT transport.

Strings without a scheme are tested against Telegram in this order: SOCKS5,
HTTP CONNECT, then SOCKS4. The first type that completes a Telethon connection
and Telegram authorization-state RPC is saved on the account. Explicit schemes
test only their mapped type.

Proxy passwords are stored in the local SQLite database because Telethon needs
them when reconnecting. They are never displayed by the bot or written to
application logs. Protect the database file and host filesystem accordingly.

## Message Scheduling

The scheduler runs automatically and:
1. Checks all active chats every 60 seconds (configurable)
2. If a chat's cooldown has expired, sends its assigned template
3. Logs success or failure
4. Updates chat status based on results

## Logging

All message sends, errors, and actions are logged to:
- Console (development)
- `logs/` directory (file-based)
- SQLite database (queryable via the bot)

## Development

### Verification

```bash
python -m pip check
python -m compileall -q main.py app
python -m unittest discover -v
python main.py
```

The project has lightweight standard-library unit tests plus the manual Telegram
test suite in `TESTING.md`.

### Enabling Production Mode

Set these in `.env`:
```
DRY_RUN=False
LOG_LEVEL=INFO
```

### Contributing

Keep the code:
- Simple and readable
- Modular and DRY
- Well type-hinted
- Properly logged

## Legal Notice

This tool is designed ONLY for sending promotional messages to Telegram groups where:
- Promotional posts are explicitly allowed in group rules
- Group administrators have approved advertising
- Your messages comply with Telegram's Terms of Service

Do NOT use this tool to:
- Spam or mass-message users
- Bypass Telegram's restrictions
- Evade moderation or detection
- Send unsolicited messages

## License

Internal use only.
