# LINE to Nextcloud Backup Bot

A LINE bot that backs up media and links to your Nextcloud. It receives images, videos, audio, files, and text messages containing URLs, downloads content from LINE (before it expires), and uploads everything to your Nextcloud via WebDAV. All backups are organized by source, date, and type.

## Project overview

- **Purpose**: Persist LINE media and important links to your own Nextcloud so you don’t lose them when LINE content expires.
- **Flow**: LINE → webhook → bot downloads (or reads text) → uploads to Nextcloud → optional reply to user. No media is kept on the server; only a small optional state file (e.g. source selection) is stored locally.
- **Stack**: Python 3.11, FastAPI, LINE Bot SDK, `requests` for WebDAV. Runs in Docker or locally with uvicorn.

## Features

- **Webhook** at `POST /callback` for the LINE platform.
- **Media**: Handles **ImageMessage**, **VideoMessage**, **AudioMessage**, **FileMessage** — downloads binary via LINE Messaging API and uploads to Nextcloud.
- **Links**: Text messages that contain `http://` or `https://` are saved as `.txt` files (full message body) under `LINE_Backup/{source}/YYYY-MM-DD/link/`.
- **Folder layout**: Uploads go under **`LINE_Backup/{source}/YYYY-MM-DD/{type}/`** where:
  - `{source}` = e.g. `Amigo`, `Ben`, `other` (set by sending "1", "2", or "0"/"other" before media).
  - `{type}` = `image`, `video`, `link`, or `files` (images in `image/`, videos in `video/`, links in `link/`, audio and documents in `files/`).
- **Filenames**: Images/videos use a short prefix and timestamp (e.g. `img_20250224_143052_123.jpg`). **Files** (PDF, PPTX, etc.) keep the **original filename only** (e.g. `Report_Q1.pptx`); the date is already in the path.
- **Source folders**: Configure `SOURCE_MAP=1:Amigo,2:Ben,3:Mom` in `.env`. Send **"1"** then forward media → saved under `LINE_Backup/Amigo/...`. Send **"0"** or **"other"** to use `other`. Optional persistence via `SOURCE_STATE_FILE` so the chosen source survives restarts.
- **Optional replies**: Set `ENABLE_LINE_REPLIES=true` to get a reply and a push message per backup (uses 2 sends per item). Default `false` = silent, to save LINE send quota.
- **Reliability**: Retries Nextcloud upload up to 3 times on failure; skips duplicate webhook events by `message_id`; streams large files via a temp file to limit memory use; container runs as non-root and includes a health check.

## Prerequisites

- **LINE**: Create a [Messaging API Channel](https://developers.line.biz/) and obtain **Channel Secret** and **Channel Access Token**.
- **Nextcloud**: Create an **App Password** (Settings → Security → App passwords) for this bot; do not use your main account password.

## Setup

1. **Clone or copy this project**, then create `.env` from the example:

   ```bash
   cp .env.example .env
   ```

2. **Edit `.env`** and set:

   - `LINE_CHANNEL_SECRET` — from LINE Developers Console (Channel → Basic settings).
   - `LINE_CHANNEL_ACCESS_TOKEN` — from LINE Developers Console (Messaging API tab).
   - `NEXTCLOUD_URL` — e.g. `https://your-nextcloud.example.com` (base URL only).
   - `NEXTCLOUD_USER` — your Nextcloud username.
   - `NEXTCLOUD_PASSWORD` — **App Password** from Nextcloud (Settings → Security → App passwords).
   - `NEXTCLOUD_BASE_PATH` — optional; default `LINE_Backup` (folder under your WebDAV root).

3. **Run locally** (optional):

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```

4. **Set LINE Webhook URL** in LINE Developers Console (Messaging API) to:

   - `https://your-public-host/callback`  
   (must be HTTPS; use ngrok or a reverse proxy for local testing).

## Docker

The project can be run fully with Docker. Timezone is `Asia/Taipei`; port 8000.

**Build and start (recommended):**

```bash
cd /path/to/line-nextcloud-bot
# Ensure .env is configured (see Environment variables below)
docker compose up -d --build
```

**Build only:**

```bash
docker compose build
# or
docker build -t line-nextcloud-bot .
```

**Start only (after build):**

```bash
docker compose up -d
```

The app listens on `0.0.0.0:8000` inside the container. `docker-compose.yml` reads `.env` and runs the container as the **host user** (via `UID`/`GID`) so that `./data` is writable. **To fix "permission denied" when saving the source map:**

1. On the host, run: `id -u` and `id -g` (e.g. `1000` and `1000`).
2. Add to `.env`: `UID=1000` and `GID=1000` (use your actual numbers).
3. Ensure the data directory exists and is yours: `mkdir -p data`
4. Restart: `docker compose up -d --build`

Then the container runs as your user and can write to `./data`.

## Environment variables

| Variable | Description |
|----------|-------------|
| `LINE_CHANNEL_SECRET` | LINE Channel Secret |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Channel Access Token |
| `NEXTCLOUD_URL` | Nextcloud base URL (e.g. `https://nc.example.com`) |
| `NEXTCLOUD_USER` | Nextcloud username |
| `NEXTCLOUD_PASSWORD` | Nextcloud App Password |
| `NEXTCLOUD_BASE_PATH` | Base folder under WebDAV (default: `LINE_Backup`) |
| `ENABLE_LINE_REPLIES` | `true` = reply + push per backup (debug); `false` = silent (default) |
| `SOURCE_MAP` | e.g. `1:Amigo,2:Ben,3:Mom` — send "1" then media → Amigo folder; "0"/"other" → other (used if SOURCE_MAP_FILE missing) |
| `SOURCE_MAP_FILE` | Optional. e.g. `data/source_map.json` — if file exists, overrides SOURCE_MAP; editable in browser at **/admin** |
| `SOURCE_STATE_FILE` | Optional. e.g. `data/source_state.json` to persist source across restarts; empty = off |
| `MAX_FILE_SIZE_MB` | Optional. Max file size in MB (0 = no limit). Larger files are skipped |
| `ADMIN_PASSWORD` | Optional. Password for **/admin** (source mapping UI). Empty = no auth (use only on trusted network) |
| `GITHUB_REPO` | Optional. GitHub repo URL shown in the home page footer (e.g. for demo / side project) |

## LINE Messaging API usage

- **Receive** (webhook, get content): Does not count against send quota.
- **Send**: Only when `ENABLE_LINE_REPLIES=true` (2 messages per backup: reply + push). Default `false` avoids using send quota. Turn on for debugging, then set back to `false`.

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Service info |
| `GET` | `/health` | Health check: 200 if Nextcloud is reachable (PROPFIND), else 503. Used by Docker Compose for container health. |
| `GET` / `POST` | `/admin` | **Source mapping UI**: view and edit number → folder (e.g. 1:Amigo, 2:Ben). Optional HTTP Basic auth via `ADMIN_PASSWORD`. Saves to `SOURCE_MAP_FILE`. |
| `GET` | `/debug-webdav` | Test Nextcloud WebDAV (creates base folder) |
| `POST` | `/callback` | LINE webhook (signature-verified) |

## Data and storage

- **Media**: Not stored on the server. Flow is: LINE → temp file (during transfer) → upload to Nextcloud → temp file deleted. Only Nextcloud holds the backup; nothing accumulates locally.
- **Local state**: If `SOURCE_STATE_FILE` is set (e.g. `data/source_state.json`), a small JSON file stores user → source folder mapping. No need to clean it periodically.
- **Temp files**: Download/upload uses the system temp directory; files are deleted after success or failure, so they do not grow over time.

## Source mapping (admin UI)

You can edit the **number → folder** mapping (e.g. 1=Amigo, 2=Ben) without touching `.env`:

1. Open **`https://your-bot-host/admin`** in a browser.
2. If you set `ADMIN_PASSWORD` in `.env`, the browser will prompt for a password (use any username, e.g. `admin`, and the password you set).
3. Edit the text area (one line per mapping: `number: FolderName`), then click **Save**. Changes take effect immediately and are stored in `data/source_map.json` (or `SOURCE_MAP_FILE`). No restart needed.

This is useful for non-technical users: they can change folder names or add new numbers without editing env or code.

## Tips

- **After restart**: With `SOURCE_STATE_FILE` set, the last source number is restored; without it, source is in-memory only.
- **Logs**: Success lines show `Backup ok: LINE_Backup/...`; failures show `Backup failed` and a stack trace. Use `docker compose logs -f` or the uvicorn console.
- **Multiple instances**: If you run more than one instance for the same bot, source state is not shared; prefer a single instance.
- **Duplicate events**: When LINE resends the same webhook, the bot skips already-processed messages by `message_id` so the same file or link is not backed up twice.

## Deployment and secrets

- **Never commit `.env`** — it contains secrets (LINE tokens, Nextcloud password, admin password). Use `.env.example` as a template and fill values on the server or in your CI.
- **Where to set variables**: Copy `.env.example` to `.env`, edit with your real values. For Docker, ensure `.env` is on the host and passed into the container (e.g. `env_file: .env` in `docker-compose.yml`).
- **Restart after changing .env**: The app reads env at startup; run `docker compose up -d --build` or restart uvicorn after editing `.env`.

## Optional: health check alert

If you want to be notified when the bot or Nextcloud is down, run a cron job that calls `/health` and alerts on failure:

```bash
# Example: every 5 minutes, alert if /health returns non-200
*/5 * * * * curl -sf https://your-bot-host/health || echo "LINE Backup health check failed"
```

You can pipe the failure into a script that sends email, Slack, or Telegram (e.g. `curl ... || send_alert.sh`).

## Push to GitHub

1. **Do not commit `.env`** (it is in `.gitignore`; use `.env.example` as a template).
2. Create a new repo on GitHub (e.g. `line-nextcloud-backup`), then:

```bash
cd /path/to/line-nextcloud-bot
git init
git add .
git commit -m "Initial commit: LINE to Nextcloud backup bot"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/line-nextcloud-backup.git
git push -u origin main
```

3. If the repo already exists, add the remote and push as needed.

## Running tests

From the project root (with dependencies installed):

```bash
pip install -r requirements.txt
pytest tests/ -v
```

Tests cover `nextcloud` helpers, `auth` (login / rate limit), `hash_store`, and `processed_ids` without hitting real LINE or Nextcloud.

## License

Use and modify as you like.
