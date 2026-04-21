# Telegram Moderation Bot

A modular Telegram moderation bot built with aiogram.  
Supports mute, kick, ban, internal moderation levels, moderation history, active mute recovery, and flexible user resolution by reply, username, or user ID.

## Features

- mute / unmute system
- kick users
- ban / unban users
- timed bans with automatic unban and restart recovery
- user message cleanup for level `4+` moderators
- internal moderation levels (`1-5`)
- support for reply / username / `user_id`
- moderation action history
- active mute tracking and recovery after restart
- optional cleanup for user command messages
- configurable `SYSTEM_OWNER_USER_ID`
- SQLite persistence with repository-based architecture
- long polling runtime for stable VPS deployment

## Architecture

The project is split into focused modules to keep the bot maintainable and production-ready:

- `handlers` - Telegram update handling and orchestration
- `services` - business logic, moderation rules, permissions, parser, scheduler, message generation
- `database` - schema, migrations, repositories, persistence models
- `utils` - constants, formatters, validators, Telegram helpers
- `middlewares` - shared ingestion and error handling

This separation keeps Telegram API calls, permission rules, persistence, and message formatting out of each other's way.

## Project Structure

```text
moderationbot/
│
├── handlers/
├── services/
├── database/
├── middlewares/
├── utils/
│
├── main.py
├── config.py
├── requirements.txt
├── .env.example
└── README.md
```

## Installation

Clone the repository and set up a local environment:

```bash
git clone https://github.com/your-name/telegram-moderation-bot.git
cd telegram-moderation-bot
python -m venv .venv
```

Activate the virtual environment:

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Linux / macOS:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## Configuration

The bot is configured through a `.env` file.

1. Copy the example file:

```bash
cp .env.example .env
```

Windows PowerShell alternative:

```powershell
Copy-Item .env.example .env
```

2. Fill in at least:

```env
BOT_TOKEN=your_token_here
SYSTEM_OWNER_USER_ID=5300889569
EXPIRED_BAN_CHECK_SECONDS=60
```

Important configuration notes:

- `BOT_TOKEN` is required
- `SYSTEM_OWNER_USER_ID` is treated as the permanent internal level `5`
- `EXPIRED_BAN_CHECK_SECONDS` controls how often the scheduler checks for expired timed bans
- warning and validation bot messages are auto-deleted after `ORDINARY_MESSAGE_DELETE_SECONDS`
- moderation results, help, start, info, history, level outputs, and cleanup results remain persistent
- `DELETE_COMMAND_MESSAGES`, if enabled, applies only to user command messages, not messages sent by the bot

## Running the Bot

Start the bot with long polling:

```bash
python main.py
```

## Verification

Run the built-in verification suite:

```bash
python tools/verify_project.py
```

Run unit tests:

```bash
python -m unittest discover -s tests -v
```

## VPS Deployment via Termius

Recommended Linux flow for a clean VPS deployment:

### 1. Connect to the server

Open an SSH session to your VPS in Termius.

### 2. Install Python and base packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

### 3. Create a project directory

```bash
mkdir -p ~/apps/moderationbot
cd ~/apps/moderationbot
```

### 4. Upload the project

Upload the repository files to `~/apps/moderationbot` using SFTP in Termius.

### 5. Create the virtual environment and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 6. Create the environment file

```bash
cp .env.example .env
nano .env
```

Set at least:

- `BOT_TOKEN`
- `SYSTEM_OWNER_USER_ID`
- `DATABASE_PATH`
- `LOG_LEVEL`

### 7. Verify before first launch

```bash
source .venv/bin/activate
python tools/verify_project.py
```

### 8. Run the bot manually

```bash
source .venv/bin/activate
python main.py
```

## Keeping the Bot Running

### Option 1. tmux

```bash
sudo apt install -y tmux
cd ~/apps/moderationbot
tmux new -s moderationbot
source .venv/bin/activate
python main.py
```

Detach with `Ctrl+B`, then `D`.

Reattach:

```bash
tmux attach -t moderationbot
```

### Option 2. systemd

Create a service file:

```bash
sudo nano /etc/systemd/system/moderationbot.service
```

Example:

```ini
[Unit]
Description=Telegram Moderation Bot
After=network.target

[Service]
Type=simple
User=YOUR_LINUX_USER
WorkingDirectory=/home/YOUR_LINUX_USER/apps/moderationbot
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/YOUR_LINUX_USER/apps/moderationbot/.venv/bin/python main.py
Restart=always
RestartSec=5
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
```

Enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable moderationbot
sudo systemctl start moderationbot
sudo systemctl status moderationbot
```

View logs:

```bash
journalctl -u moderationbot -f
```

## Telegram Bot API Limitations

This project stays honest about Telegram limitations:

- the bot cannot browse arbitrary old chat history retroactively
- cleanup uses only messages the bot has already seen and stored in the lightweight message reference cache
- username lookup works only for users the bot has already seen and cached
- moderation actions against chat owners or some admins may still be blocked by Telegram itself
- user moderation commands do not work in channels

For the most reliable targeting, prefer:

1. reply to a message
2. `user_id`
3. cached `username`

## Notes

- user-facing bot messages are implemented in Russian
- persistence is SQLite-first, with repositories prepared for future database evolution
- startup includes migration execution, mute recovery, and scheduler bootstrap 
