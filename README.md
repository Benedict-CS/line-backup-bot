# LINE to Nextcloud Backup Bot

LINE Bot that receives image / video / audio / file messages, downloads the content from LINE, and uploads it to your Nextcloud via WebDAV. Use it to avoid losing media when LINE content expires.

**Repo name suggestion:** `line-nextcloud-backup` or `line-backup-bot`

## Features

- **Webhook** at `POST /callback` for LINE Platform
- Handles **ImageMessage**, **VideoMessage**, **AudioMessage**, **FileMessage**
- Downloads binary content via LINE Messaging API
- Uploads to Nextcloud under **`LINE_Backup/YYYY-MM-DD/`** (filename includes time)
- Optional replies: set `ENABLE_LINE_REPLIES=true` to get "收到檔案..." and "✅ 已備份" (uses 2 sends per file); default `false` = silent
- **Source folders**: set `SOURCE_MAP=1:Amigo,2:Ben,3:Mom` in `.env`. Send **"1"** then forward media → saved under `LINE_Backup/Amigo/date/`. Send **"0"** or **"other"** → back to `other`. No number before media → `other`

## Prerequisites

- LINE Developers: create a **Messaging API Channel** and get **Channel Secret** and **Channel Access Token**
- Nextcloud: create an **App Password** (Settings → Security → App passwords) for this bot; do not use your main login password

## Setup

1. **Clone or copy this project**, then create `.env` from the example:

   ```bash
   cp .env.example .env
   ```

2. **Edit `.env`** and set:

   - `LINE_CHANNEL_SECRET` – from LINE Developers Console (Channel → Basic settings)
   - `LINE_CHANNEL_ACCESS_TOKEN` – from LINE Developers Console (Messaging API tab)
   - `NEXTCLOUD_URL` – e.g. `https://your-nextcloud.example.com`
   - `NEXTCLOUD_USER` – your Nextcloud username
   - `NEXTCLOUD_PASSWORD` – **App Password** from Nextcloud (Settings → Security → App passwords)
   - `NEXTCLOUD_BASE_PATH` – optional, default `LINE_Backup` (folder under your WebDAV root)

3. **Install dependencies and run** (local):

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```

4. **LINE Webhook URL**: set your Webhook URL in LINE Developers Console (Messaging API) to:

   - `https://your-public-host/callback`  
   (must be HTTPS; use ngrok or a reverse proxy for local testing)

## Docker (Proxmox / TrueNAS)

專案已可完整以 Docker 部署，時區為 `Asia/Taipei`，埠號 8000。

**建置並啟動（建議）：**

```bash
cd /home/ben/line-nextcloud-bot
# 請先設定好 .env（或依下方環境變數）
docker compose up -d
```

**僅建置映像：**

```bash
docker compose build
# 或
docker build -t line-nextcloud-bot .
```

**僅啟動（已建置過）：**

```bash
docker compose up -d
```

容器內服務監聽 `0.0.0.0:8000`。`docker-compose.yml` 會讀取同目錄下的 `.env`，並設定 `TZ=Asia/Taipei` 與 LINE / Nextcloud 相關環境變數。

## Environment variables

| Variable | Description |
|----------|-------------|
| `LINE_CHANNEL_SECRET` | LINE Channel Secret |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Channel Access Token |
| `NEXTCLOUD_URL` | Nextcloud base URL (e.g. `https://nc.example.com`) |
| `NEXTCLOUD_USER` | Nextcloud username |
| `NEXTCLOUD_PASSWORD` | Nextcloud App Password |
| `NEXTCLOUD_BASE_PATH` | Base folder name under WebDAV (default: `LINE_Backup`) |
| `ENABLE_LINE_REPLIES` | `true` = reply + push per file (debug); `false` = silent (default) |
| `SOURCE_MAP` | `1:Amigo,2:Ben,3:Mom` = send "1" then media → Amigo folder; "0"/"other" → other |
| `SOURCE_STATE_FILE` | Optional. e.g. `data/source_state.json` = persist source so restart keeps last number; empty = off |
| `MAX_FILE_SIZE_MB` | Optional. Max file size in MB (0 = no limit). Larger files are skipped |

## LINE Messaging API 用量

- **接收**（Webhook、Get content 下載）：不計入發送配額。
- **發送**：僅在 `ENABLE_LINE_REPLIES=true` 時會發送（每則備份 2 則：reply + push）。預設 `false` 不發送，不會消耗發送配額。
- 除錯時可設 `ENABLE_LINE_REPLIES=true`，確認後改回 `false` 即可。

## API

- `GET /` – Service info
- `GET /health` – **Health check**: 200 if Nextcloud reachable (PROPFIND), else 503
- `GET /debug-webdav` – Test Nextcloud WebDAV (create base folder)
- `POST /callback` – LINE Webhook (signature-verified)

## Tips / 注意

- **重啟後**：若設了 `SOURCE_STATE_FILE`（如 `data/source_state.json`），編號會寫入檔案，重啟後不用再傳編號。不設則只存在記憶體。
- **看日誌**：成功會打 `Backup ok: LINE_Backup/...`，失敗會打 `Backup failed` 與錯誤堆疊，方便除錯（`docker compose logs -f` 或 uvicorn 終端）。
- **多台機器**：若同一 Bot 跑多個 instance，來源編號不會共用，建議只跑一個 instance。

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

3. If the repo already exists and you already have commits, just add the remote and push.

## License

Use and modify as you like.
