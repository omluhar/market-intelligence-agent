# Market Intelligence Council

Autonomous paper-trading desk: fundamental Scout, tactical momentum, deterministic risk checks, and a DuckDB execution ledger.

The production build is a **single website**. Next.js is statically exported and FastAPI serves both the UI and `/api/v1`.

## Live / production

The app is on GitHub at [omluhar/market-intelligence-agent](https://github.com/omluhar/market-intelligence-agent).

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/omluhar/market-intelligence-agent)

That button builds the Docker image (Next.js UI + FastAPI API on one URL). After the first deploy, set `OPENAI_API_KEY` in the Render dashboard so Scout can reason.

You can also run the same image locally:

```bash
docker build -t market-intelligence-agent .
docker run --rm -p 8000:8000 \
  -e OPENAI_API_KEY=sk-... \
  -e DRY_RUN=true \
  market-intelligence-agent
```

Then open `http://localhost:8000`.

The included `render.yaml` deploys that same image to [Render](https://render.com). Set `OPENAI_API_KEY` in the Render dashboard after connecting this GitHub repo.

### Persistent memory on Render (recommended)

By default Render’s filesystem is **ephemeral** — when the service sleeps, DuckDB files disappear and pause state, portfolio sync, and research logs reset.

The repo’s `render.yaml` attaches a **1 GB persistent disk** at `/var/data` and sets:

```bash
DUCKDB_PATH=/var/data/orders.db
```

After deploy, confirm in the Render dashboard:

1. **Disks** — `mic-data` mounted at `/var/data`
2. **Environment** — `DUCKDB_PATH=/var/data/orders.db`

Everything below lives in that one file:

| Table / data | Purpose |
| --- | --- |
| `agent_settings` | Pause/resume, last sweep timestamp |
| `agent_events` | Scan history, portfolio analyses, catch-up sweeps |
| `orders` | Paper trading ledger (training data) |
| `recommendations` | Saved scout/tactical ideas |
| `portfolio_*` | Robinhood accounts, holdings, insights |
| `portfolio_chat_messages` | Portfolio advisor chat history |

**Agents default to paused** on a fresh database so a cold start never burns credits. Click **Resume agents** when you want research to run. If research is stale by 24+ hours, resume triggers a **catch-up sweep**.

To back up: download `/var/data/orders.db` from a one-off shell, or migrate later to [Render Postgres](https://render.com/docs/postgresql) for larger retention.

## Local development

Use two processes so the Next.js dev server can hot-reload:

```bash
python3 -m venv venv
./venv/bin/pip install -r backend/requirements.txt
cp backend/.env.example backend/.env   # then add OPENAI_API_KEY
./venv/bin/uvicorn backend.app.main:app --reload --port 8000
```

```bash
cd frontend
npm install
npm run dev
```

The dashboard at `http://localhost:3000` calls `http://127.0.0.1:8000`. CORS is already enabled for that origin.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness |
| POST | `/api/v1/scan/{ticker}` | Dual-agent council scan |
| GET | `/api/v1/history/{ticker}` | Daily OHLCV |
| GET | `/api/v1/recommendations` | Screener |
| POST | `/api/v1/sweep` | Background universe sweep |
| GET/POST/DELETE | `/api/v1/watchlist` | Watchlist |
| GET | `/api/v1/orders` | Paper-trade ledger |
