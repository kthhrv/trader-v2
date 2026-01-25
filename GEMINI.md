# Gemini Context & Conventions (V2)

## Architecture Overview
V2 follows a modular service-oriented architecture with clear separation between Domain models, Data access, and External adapters.

## Key Changes & Technical Debt (Resolved)
- **Interactive Confirmation in Engine**: (FIXED) Refactored `StrategyEngine` to use a callback pattern. UI logic (Confirmation) now resides in `app/cli/trade.py`. The Engine is now purely non-interactive and decoupled from the CLI.

## Current Technical Debt & Future Actions
- **Security: Session Token Exposure**: Node.js streamer processes currently receive CST/XST tokens via command-line arguments, exposing them in `ps aux`. 
    - **Future Action**: Refactor `StreamManager` to pass tokens via Environment Variables or `stdin`.
- **Infrastructure: Database Scalability**: SQLite (even in WAL mode) may face concurrency bottlenecks as the number of monitored markets increases.
    - **Future Action**: Migrate to external PostgreSQL/TimescaleDB.

## Tech Stack
- **Python**: 3.12+
- **Database**: SQLModel (SQLite)
- **AI**: Google Gemini (via `google-genai` SDK)
- **Testing**: pytest
- **TypeCheck**: astral-ty
- **Linting**: ruff
