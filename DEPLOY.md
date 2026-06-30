# First VPS Deployment

Target: Ubuntu 24.04 LTS, Python 3.13, SQLite, systemd.

The first deployment must stay in `DRY_RUN=True` until all Telegram and proxy
accounts have been checked manually.

## 1. Prepare Ubuntu

Ubuntu 24.04 ships Python 3.12 as its default interpreter. Install Python 3.13
without replacing the system Python. The official Python documentation
recommends `make altinstall` for a parallel source installation.

```bash
sudo apt update
sudo apt install -y \
  build-essential pkg-config wget ca-certificates \
  libssl-dev zlib1g-dev libbz2-dev libreadline-dev \
  libsqlite3-dev libffi-dev liblzma-dev tk-dev uuid-dev

cd /tmp
wget https://www.python.org/ftp/python/3.13.14/Python-3.13.14.tgz
tar -xzf Python-3.13.14.tgz
cd Python-3.13.14
./configure --enable-optimizations
make -j"$(nproc)"
sudo make altinstall
python3.13 --version
```

Install Git and create a dedicated service account:

```bash
sudo apt install -y git
sudo useradd --system --create-home \
  --home-dir /opt/cex-restore-panel \
  --shell /usr/sbin/nologin cexrestore
```

## 2. Clone and install

Replace `YOUR_REPOSITORY_URL` with the repository URL.

```bash
sudo git clone YOUR_REPOSITORY_URL /opt/cex-restore-panel
sudo chown -R cexrestore:cexrestore /opt/cex-restore-panel
cd /opt/cex-restore-panel
sudo -u cexrestore ./deployment/install.sh
```

`install.sh` creates `.venv`, installs pinned dependencies, checks them, and
creates runtime directories. It never overwrites an existing `.env`.

## 3. Configure `.env`

If `install.sh` created the template, edit it:

```bash
sudoedit /opt/cex-restore-panel/.env
sudo chown cexrestore:cexrestore /opt/cex-restore-panel/.env
sudo chmod 600 /opt/cex-restore-panel/.env
```

Required values:

```dotenv
BOT_TOKEN=...
OWNER_TELEGRAM_ID=...
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
```

Keep these production-safe defaults for the first deployment:

```dotenv
DATABASE_URL=sqlite:///./data/cex_restore.db
DRY_RUN=True
LOG_LEVEL=INFO
TZ=Europe/Moscow
SESSIONS_DIR=sessions
LOGS_DIR=logs
BACKUP_DIR=backups
LOG_MAX_BYTES=10485760
LOG_BACKUP_COUNT=5
SCHEDULER_CHECK_INTERVAL_SECONDS=60
PROXY_MONITOR_INTERVAL_SECONDS=1800
```

## 4. Initialize and verify

The smoke test creates missing directories, initializes the database, starts
and stops the scheduler and proxy monitor, and constructs the aiogram bot. It
does not connect to Telegram.

```bash
cd /opt/cex-restore-panel
sudo -u cexrestore .venv/bin/python scripts/smoke_test.py
sudo -u cexrestore .venv/bin/python scripts/healthcheck.py
```

Migrations also run automatically on every normal startup. A separate manual
`mkdir` or database creation command is not required.

## 5. Run manually

```bash
cd /opt/cex-restore-panel
sudo -u cexrestore ./deployment/start.sh
```

Stop the foreground process with `Ctrl+C`. It shuts down polling, the proxy
monitor, scheduler, cached Telethon clients, and the HTTP session.

## 6. Install the systemd unit

The supplied unit assumes user `cexrestore` and path
`/opt/cex-restore-panel`. Edit the unit first if either differs.

```bash
cd /opt/cex-restore-panel
sudo cp deployment/systemd/cex-restore.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cex-restore.service
sudo systemctl status cex-restore.service
```

Logs are written to both journald and rotating files:

```bash
sudo journalctl -u cex-restore.service -f
tail -f /opt/cex-restore-panel/logs/cex-restore.log
```

## 7. Update procedure

The update script creates a safe backup, performs only a fast-forward Git pull,
installs requirements, and runs the offline smoke test. It refuses to modify a
running deployment and does not restart the service automatically.

```bash
cd /opt/cex-restore-panel
sudo ./deployment/stop.sh
sudo -u cexrestore ./deployment/update.sh
sudo ./deployment/restart.sh
```

## 8. Backup procedure

```bash
cd /opt/cex-restore-panel
sudo -u cexrestore ./deployment/backup.sh
```

Each timestamped directory under `backups/` contains:

- a consistent SQLite backup as `cex_restore.db`;
- consistent copies of Telethon `*.session` databases;
- `.env.backup`, protected with mode `600`.

Backups contain credentials and Telegram sessions. Copy them to encrypted
off-server storage and never commit them to Git.

## 9. Restore procedure

Choose one backup directory and replace `BACKUP_DIRECTORY` below:

```bash
cd /opt/cex-restore-panel
sudo ./deployment/stop.sh
sudo -u cexrestore ./deployment/backup.sh

sudo -u cexrestore cp BACKUP_DIRECTORY/cex_restore.db data/cex_restore.db
sudo -u cexrestore cp BACKUP_DIRECTORY/sessions/*.session sessions/
sudo chown -R cexrestore:cexrestore data sessions
sudo chmod 700 data sessions
sudo chmod 600 data/cex_restore.db sessions/*.session

sudo -u cexrestore .venv/bin/python scripts/smoke_test.py
sudo ./deployment/start.sh
```

Restore `.env.backup` only when intentionally restoring credentials. Inspect
it first and keep file mode `600`.

## 10. Service commands

```bash
sudo ./deployment/status.sh
sudo ./deployment/stop.sh
sudo ./deployment/restart.sh
```

## 11. Troubleshooting

### Configuration error without traceback

Run:

```bash
sudo -u cexrestore .venv/bin/python scripts/healthcheck.py
```

Correct every `[FAIL]` item in `.env` or filesystem permissions.

### Permission denied for database, sessions, logs, or backups

```bash
sudo chown -R cexrestore:cexrestore \
  /opt/cex-restore-panel/data \
  /opt/cex-restore-panel/sessions \
  /opt/cex-restore-panel/logs \
  /opt/cex-restore-panel/backups
```

### Bot repeatedly restarts

```bash
sudo journalctl -u cex-restore.service -n 200 --no-pager
sudo -u cexrestore .venv/bin/python scripts/smoke_test.py
```

### SQLite is locked

Confirm only one bot instance is running:

```bash
sudo systemctl status cex-restore.service
pgrep -af 'python.*main.py'
```

Do not run a second manual bot while the systemd service is active.

### Telegram or proxy connectivity

The smoke test deliberately does not use the network. After systemd starts,
perform Telegram authorization and proxy checks through the operator UI and
inspect the application log for safe diagnostics.
