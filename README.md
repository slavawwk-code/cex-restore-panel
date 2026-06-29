# Cex Restore Panel

Internal Telegram CRM for managing advertising campaigns using multiple Telegram user accounts.

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

## Technology Stack

- Python 3.13+
- aiogram 3 (Telegram bot framework)
- Telethon (Telegram user account client)
- SQLite (database)
- APScheduler (task scheduling)
- SQLAlchemy (ORM)

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
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Required configuration:
- `BOT_TOKEN`: Your Telegram bot token (get from BotFather)
- `TELETHON_API_ID`: Your Telegram API ID (get from my.telegram.org)
- `TELETHON_API_HASH`: Your Telegram API Hash (get from my.telegram.org)
- `OWNER_TELEGRAM_ID`: Your Telegram user ID (get from @userinfobot)

### 3. Initialize Database

```bash
python -c "from app.database.models import init_db; init_db()"
```

### 4. Run the Bot

```bash
python main.py
```

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

### Running Tests

```bash
pytest tests/
```

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
