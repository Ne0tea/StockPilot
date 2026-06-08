# StockPilot

StockPilot is a local stock analysis workspace built with `FastAPI`, `Vue 3`, and `SQLite`. It combines watchlist management, portfolio tracking, AI-assisted daily analysis, report history, and scheduled notifications in a single web app.

The current project is centered on a runnable local product, not a GitHub Actions template. It provides:

- A web dashboard for watchlists, reports, portfolio activity, settings, and agent chat
- A backend service for task orchestration, report persistence, notification delivery, and streaming updates
- Daily stock analysis flows, interactive analysis sessions, and portfolio-focused specialist analysis

## What StockPilot Is For

StockPilot is a good fit if you want to:

- Maintain a personal watchlist and accumulate daily stock reports
- Track portfolio positions alongside analysis outcomes
- Keep structured analysis history instead of relying on chat logs alone
- Deliver daily summaries by email or WeCom webhook
- Run deeper, context-aware agent analysis against active holdings

## Core Capabilities

### Watchlist Management

- Add and remove stocks from the active watchlist
- Resolve stocks by code or name
- Trigger analysis for one stock or the full watchlist
- Clear analysis history for one stock or the whole workspace

### Daily Analysis and Report Archiving

- Parse AI-generated markdown into structured report summaries
- Persist daily reports into SQLite for dashboard and history views
- Save markdown and HTML report artifacts for later inspection
- Surface latest and historical reports in the web UI

### Portfolio Tracking

- Record buy and sell trades
- Maintain open and closed positions
- Build cumulative profit history
- Show position-aware recommendations separately from watchlist signals

### Notifications and Scheduling

- Schedule a daily summary with APScheduler
- Deliver results through email or WeCom webhook
- Log notification attempts and outcomes
- Highlight missing or incomplete daily reports in the summary

### Specialist Agent Analysis

- Launch portfolio-aware specialist sessions for held stocks
- Build prompts from holding cost, position size, buy date, and latest report price
- Stream intermediate status and final results back to the frontend

## Inputs, Execution Flow, and Outputs

This project is easiest to understand through its three main operating flows.

### 1. Watchlist Daily Analysis

#### Inputs

Users add stocks from the Stocks page with:

- Stock code such as `600519` or `AAPL`
- Market value
- Stock name

#### Execution Flow

1. The frontend creates or updates watchlist entries through `/api/watchlist`.
2. A user triggers analysis for one stock or all active stocks.
3. The backend enqueues work and processes it in FIFO order.
4. The daily analysis path starts a local Claude CLI run.
5. In the intended analysis workflow, that Claude run invokes the `stock-analysis` skill to perform the daily stock analysis.
6. The generated markdown is parsed into structured fields such as total score, action, rationale, entry price, target price, stop-loss price, and current price.
7. Structured data is saved to SQLite, while markdown and optional HTML reports are saved as artifacts.
8. The frontend polls status endpoints and listens to SSE streams for progress and completion.

#### Output

This flow produces:

- A structured daily report record in the database
- A markdown report file
- An HTML report when available
- Dashboard-ready recommendation data for both watchlist and portfolio views

### 2. Portfolio Tracking

#### Inputs

Users record trades from the Portfolio page with:

- Stock code
- Stock name
- Buy or sell action
- Trade price
- Share count
- Trade date

#### Execution Flow

1. The frontend submits trades to `/api/portfolio/trade`.
2. The backend stores raw trade events.
3. Portfolio holdings are updated based on the new trade.
4. Dashboard views combine portfolio data with the latest available stock reports.
5. Held stocks can then be analyzed further through the specialist agent workflow.

#### Output

This flow produces:

- Current holdings and closed positions
- Cumulative profit history
- Portfolio-aware recommendation views
- Context for specialist agent analysis

### 3. Settings and Scheduled Delivery

#### Inputs

Users configure settings from the Settings page, including:

- SMTP sender email, password, and recipient addresses
- WeCom webhook URL
- Daily schedule time
- Daily report LLM settings
- Specialist agent OpenAI-compatible settings
- TickFlow API key

#### Execution Flow

1. The frontend updates settings through `/api/settings`.
2. The backend persists the values to SQLite.
3. Schedule changes are applied immediately to the running scheduler.
4. Daily report LLM settings are synchronized to the Claude settings file used by the report workflow.
5. At the configured time, the scheduler builds a daily summary from the latest completed reports.
6. Notification senders deliver that summary through the configured channels.
7. Delivery results are stored for later inspection in the UI.

#### Output

This flow produces:

- Scheduled daily summaries
- Email or WeCom deliveries
- Notification history and delivery logs
- Visibility into missing daily analyses

## What Users See in the Web App

### Dashboard

- Portfolio recommendations
- Watchlist signals
- Cost distribution and profit history charts
- Delivery and notification history

### Stocks

- Watchlist editing
- Per-stock daily status
- Single-stock and bulk analysis triggers
- Streaming progress for active analysis
- Links to report history

### Reports

- Full report history
- Filtering by stock and date range
- Rescanning saved reports into the database index

### Portfolio

- Trade entry
- Current holdings and closed positions
- Profit history

### Settings

- Notification configuration
- Daily schedule configuration
- Daily report LLM configuration
- Specialist analysis LLM configuration
- TickFlow key management

## Data and Persistent Outputs

### Database

The web application uses a SQLite database at:

- `backend/data/stock_analysis_app.db`

Important persisted entities include:

- Watchlist items
- Daily stock report summaries
- Analysis task states
- Portfolio positions
- Trade logs
- User settings
- Delivery records
- Notification logs

### Saved Reports

StockPilot stores generated reports as files in `backend/reports/`, including:

- Markdown reports for each analyzed stock and date
- HTML report artifacts when generated by the analysis flow

## Quick Start

### Clone and Start in This Environment

If you want to run the full project directly after cloning in the current environment, use:

```bash
git clone <your-repo-url>
cd Stock_analysis
bash start.sh
```

This startup script will:

- start the backend with `/home/ne0tea/miniconda3/envs/stockPanel/bin/python`
- start the frontend with `npm run dev`
- wait for both services to become available

After startup:

- Backend: `http://localhost:8000`
- Frontend: `http://localhost:5173`
- API Docs: `http://localhost:8000/docs`

Before running `bash start.sh`, make sure:

- the `stockPanel` Python environment already exists
- frontend dependencies have already been installed in `frontend/`
- Node.js and npm are available in the current shell

### Start the Backend

Use Python 3.10+.

```bash
cd backend
pip install -r requirements.txt
python main.py
```

Backend default address:

- `http://127.0.0.1:8000`

### Start the Frontend

Use Node.js 18+.

```bash
cd frontend
npm install
npm run dev
```

Frontend default address:

- `http://127.0.0.1:5173`

The Vite dev server proxies:

- `/api` to `http://127.0.0.1:8000`
- `/reports` to `http://127.0.0.1:8000`

### Open the App

Visit:

- `http://127.0.0.1:5173`

## Runtime Notes

### Local Claude CLI Is Required for Daily Analysis

The current daily report flow runs through the local `claude` executable. If Claude CLI is not installed or not available at runtime, daily stock analysis jobs will not complete successfully.

### The Daily Analysis Flow Uses the `stock-analysis` Skill

The README expectation for this project is that the daily analysis workflow calls the `stock-analysis` skill through the local Claude-based analysis path. That is the skill responsible for producing the daily stock analysis output used by StockPilot.

### Specialist Agent Analysis Requires OpenAI-Compatible Settings

The specialist agent flow depends on:

- `agent_api_key`
- `agent_base_url`
- `agent_model`

If these are not configured, specialist chat endpoints will return a configuration error.

### TickFlow Features Require a TickFlow API Key

The saved TickFlow key is applied to runtime environment configuration for K-line related capabilities.

## Main API Surface

### Watchlist

- `GET /api/watchlist`
- `GET /api/watchlist/overview`
- `POST /api/watchlist`
- `DELETE /api/watchlist/{stock_id}`
- `POST /api/watchlist/reset`

### Analysis

- `POST /api/analyze/all`
- `POST /api/analyze/{code}`
- `GET /api/analyze/queue`
- `GET /api/analyze/{code}/status`
- `POST /api/analyze/{code}/interactive`
- `GET /api/analyze/{code}/stream`
- `POST /api/analyze/{code}/respond`
- `DELETE /api/analyze/{code}/session`

### Reports

- `GET /api/reports`
- `GET /api/reports/{code}`
- `GET /api/reports/{code}/latest`
- `POST /api/reports/rescan`

### Portfolio

- `GET /api/portfolio`
- `GET /api/portfolio/profit-history`
- `POST /api/portfolio/trade`
- `GET /api/portfolio/trades`

### Settings and Notifications

- `GET /api/settings`
- `PUT /api/settings`
- `POST /api/settings/test-email`
- `POST /api/settings/test-wechat`
- `GET /api/dashboard/notifications`

### Agent

- `GET /api/agent/skills`
- `POST /api/agent/chat/start`
- `POST /api/agent/chat/start-stream`
- `POST /api/agent/chat/message`
- `GET /api/agent/chat/{session_id}/stream`

## Typical Usage Paths

### Build a Daily Watchlist Workflow

1. Add stocks from the Stocks page.
2. Configure the daily report LLM and at least one notification channel.
3. Trigger a manual run to verify output quality.
4. Set the daily schedule time.
5. Review results from the dashboard, reports page, or notification channel each day.

### Use StockPilot as a Portfolio Decision Workspace

1. Record trades in the Portfolio page.
2. Add held stocks to the watchlist so they enter the daily analysis flow.
3. Let the daily report workflow generate structured output.
4. Review position-specific guidance in the dashboard.
5. Launch specialist analysis for positions that need deeper review.

## Current Strengths and Boundaries

### Strengths

- Clear separation between UI, orchestration, persistence, and delivery
- Persistent structured history instead of ephemeral chat-only output
- Daily analysis, interactive analysis, and specialist analysis in one product
- Practical local workflow for long-running personal use

### Boundaries

- Daily analysis currently depends on a local Claude CLI workflow
- The web settings flow currently focuses on email and WeCom notification delivery
- Some advanced data-provider and agent logic requires additional external model or service configuration
