# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Development Commands

```bash
# Start all Docker stacks locally (infra, app, observability, watchdog)
inv up

# Stop all stacks
inv down

# Stream unified logs from Loki
inv logs

# Run all quality checks (ruff + ty + pytest)
inv check

# Individual checks
ruff check .
ty check
pytest

# Run a single test file
pytest tests/test_risk_manager.py

# Run a single test by name
pytest tests/test_risk_manager.py -k "test_name"

# Build Docker image locally
inv build

# Publish to private registry and deploy
inv publish
inv deploy --env=demo

# Start Reflex UI dashboard
inv ui

# Run the app directly (outside Docker)
python main.py --server          # Full execution server (listener + scheduler)
python main.py --market ftse     # One-off strategy run for a market
python main.py --watch           # Start volatility watcher
python main.py --scorecard       # Performance stats
```

## Architecture

### Core Flow: Analyze -> Validate -> Execute

The system is an autonomous trading bot for IG Markets indices (FTSE, S&P 500, DAX, ASX, Nasdaq). It uses Google Gemini AI to generate trading signals based on technical analysis and news sentiment, then executes trades via the IG REST API.

**Runtime modes** (all via `main.py`):
- **Server mode** (`--server`): Production mode. Runs the `CommandListener` (Redis subscriber) and `APScheduler` concurrently. The scheduler publishes commands to Redis at market-open times; the listener receives them and triggers `StrategyEngine.run_strategy()`.
- **Watcher** (`--watch`): Monitors Redis tick stream for volatility spikes (>0.15% in 60s). Triggers immediate AI analysis bypassing the schedule.
- **One-off** (`--market <key>`): Interactive single-market strategy run.

### Key Layers

- **`app/core/container.py`** — Manual DI container. `Container.create_strategy_engine()` wires the full dependency graph. Entry point for understanding how services connect.
- **`app/core/markets.py`** — Market configs (epic codes, schedules, spread limits, strategy assignments).
- **`app/core/config.py`** — `pydantic_settings.BaseSettings`. Loads from `.env.test` → `.env.local` → `.env`. Supports dual IG accounts (DEMO/LIVE) selected via `TRADING_ACCOUNT_ENV` and `DATA_ACCOUNT_ENV`.

- **`app/services/trader.py`** — `StrategyEngine` orchestrator. Coordinates analyzer → risk manager → executor.
- **`app/services/analyzer.py`** — `MarketAnalyzer`. Fetches market data + news, builds prompts, calls Gemini for a `TradingSignal`.
- **`app/services/executor.py`** — `TradeExecutor`. Places trades via IG client, manages stalking (re-entry) logic.
- **`app/services/risk.py`** — `RiskManager`. Position sizing, consecutive loss limits, account balance checks.
- **`app/services/watcher.py`** — `WatcherService`. Redis tick consumer, volatility spike detection.
- **`app/services/command_listener.py`** — `CommandListener`. Redis Pub/Sub subscriber that triggers strategy runs.

- **`app/adapters/ig_client.py`** — `AsyncIGClient`. Singleton HTTP client for IG Markets REST API.
- **`app/adapters/gemini_service.py`** — `GeminiService`. Calls Gemini, returns structured `TradingSignal` (action, conviction, stop/limit levels).
- **`app/adapters/news_client.py`** — RSS/feed news aggregation.
- **`app/adapters/notification.py`** — Home Assistant push notifications for alerts.
- **`app/adapters/js/`** — Node.js Lightstreamer client for real-time IG tick data, published to Redis.

- **`app/streamer/`** — Candle builder. Aggregates raw ticks from Redis into 1m/5m/15m OHLC candles in the database.

- **`app/database/`** — SQLModel models, async session management. Production uses PostgreSQL/TimescaleDB; tests use in-memory SQLite via aiosqlite.

- **`app/cli/`** — CLI command implementations dispatched from `main.py`.
- **`app/domain/models.py`** — Shared domain value objects.

### Docker Stacks (in `docker/`)

Four isolated compose stacks, layered with `.dev.yml` overrides for local development:
1. **Infra** — Redis + Market Streamer (Node.js)
2. **App** — Trader (server mode) + Watcher
3. **Observability** — Grafana + Loki + Promtail
4. **Watchdog** — Health monitor (checks Redis heartbeat, alerts via Home Assistant)

### `dashboard/`

Reflex-based web UI for monitoring P&L, signals, and market status.

## Testing

- Tests use `pytest` with `pytest-asyncio` (strict mode).
- `tests/conftest.py` auto-mocks settings and provides a per-test temp SQLite database via `aiosqlite`.
- HTTP calls to IG are mocked with `pytest-httpx`.
- Tests are organized by service/domain: `test_strategy_engine.py`, `test_risk_manager.py`, `test_executor_logic.py`, etc.

## Code Quality

- **Linter/formatter**: `ruff` (check + format)
- **Type checker**: `ty`
- **Pre-commit hooks** run ruff, ty, and pytest on every commit
- Package management: `uv` (lockfile: `uv.lock`)

## Task Runner

All orchestration uses **Invoke** (`tasks.py`). Key tasks: `up`, `down`, `logs`, `check`, `publish`, `deploy`, `build`, `ui`, `seed`.
