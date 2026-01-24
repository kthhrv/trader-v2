# Gemini Context & Conventions (V2)

## Architecture Overview
V2 follows a modular service-oriented architecture with clear separation between Domain models, Data access, and External adapters.

## Key Changes & Technical Debt (Resolved)
- **Interactive Confirmation in Engine**: (FIXED) Refactored `StrategyEngine` to use a callback pattern. UI logic (Confirmation) now resides in `app/cli/trade.py`. The Engine is now purely non-interactive and decoupled from the CLI.

## Tech Stack
- **Python**: 3.12+
- **Database**: SQLModel (SQLite)
- **AI**: Google Gemini (via `google-genai` SDK)
- **Testing**: pytest
- **TypeCheck**: astral-ty
- **Linting**: ruff
