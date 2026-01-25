# Trader V2: Autonomous Event-Driven Trading Platform

Trader V2 is a high-frequency, AI-powered trading bot built on a modular, event-driven microservices architecture. It monitors global indices 24/7, records market structure into high-resolution candlestick data, and employs Google Gemini AI to execute regime-aware strategies.

## 🏗 Architecture Overview

The system is decoupled into four primary stacks to ensure resilience, observability, and scalability:

1.  **Infra Stack:**
    *   **Redis:** The central nervous system using Pub/Sub for tick data and command distribution.
    *   **Market Streamer:** Spawns independent Node.js processes to maintain persistent Lightstreamer connections to IG Markets.
2.  **App Stack:**
    *   **Execution Server (Trader):** A centralized listener that executes AI strategy runs on command.
    *   **Reflex Engine (Watcher):** Monitors the Redis tick stream for volatility spikes (>0.15% in 60s) to trigger immediate AI reactions.
    *   **Dashboard (UI):** A modern web interface built with **Reflex** for monitoring P&L, signals, and market status.
3.  **Logging Stack (PLG):**
    *   **Loki + Promtail:** Unified log aggregation across all containers.
    *   **Grafana:** Centralized dashboard for system observability and log exploration.
4.  **Watchdog Stack:**
    *   Monitors container health and ensures 24/7 uptime.

## 🚀 Key Features

*   **Regime-Aware Intelligence:** Automatically switches between `momentum_breakout` and `mean_reversion` strategies based on ADX and Volatility Ratio indicators.
*   **Volatility Reflexes:** Bypasses scheduled runs to respond instantly to impulse moves detected by the Watcher.
*   **24/7 Market Recording:** Aggregates raw ticks into 1m, 5m, and 15m candles in a local SQLite database (WAL mode).
*   **Unified CLI Monitoring:** Stream logs from all stacks interleaved in a single terminal using `inv logs`.
*   **Production Parity:** Local development mirrors production exactly via isolated Docker project namespaces.

## 🛠 Tech Stack

*   **Language:** Python 3.12+ (managed via `uv`)
*   **Brain:** Google Gemini (using `google-genai` SDK with reasoning models)
*   **Bus:** Redis
*   **Storage:** SQLModel / SQLite (WAL mode enabled)
*   **Observability:** Grafana / Loki / Promtail
*   **Orchestration:** Invoke / Docker Compose

## 🚥 Quick Start

### 1. Prerequisites
*   [uv](https://github.com/astral-sh/uv) installed.
*   Docker and Docker Compose installed.
*   Copy `.env.example` to `.env` and fill in your IG Markets and Google Gemini API keys.

### 2. Local Development
```bash
# Start all 4 stacks (Logging, Infra, App, Watchdog)
inv up

# Stream unified logs from all containers
inv logs

# Run tests and quality checks
inv check
```

### 3. Production Deployment
The system is optimized for deployment to a remote Debian host via a private registry.
```bash
# Build multi-arch images and push to registry
inv publish

# Sync configs and orchestrate remote stacks
inv deploy

# Stream PRODUCTION logs to your local terminal
inv logs --host prod
```

## 📈 Roadmap
*   **DB Migration:** Move to external PostgreSQL/TimescaleDB.
*   **Macro Sensors:** Integrate Economic Calendars (Finnhub) for CPI/Fed triggers.
*   **Remote Control:** Telegram/Discord bot for manual interventions and P&L snapshots.

---
*Disclaimer: Trading involves significant risk. This software is provided for educational and research purposes.*
