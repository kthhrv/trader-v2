# Gemini Context & Conventions (V2)

## Architecture Overview
V2 follows a modular service-oriented architecture with clear separation between Domain models, Data access, and External adapters.

## Key Changes & Technical Debt
- **Interactive Confirmation in Engine**: `StrategyEngine.run_strategy` currently includes an `input()` call for manual confirmation when `yes_mode=False`. This violates the separation of concerns between the business logic (Engine) and the User Interface (CLI). 
    - **Future Action**: Refactor `run_strategy` to be purely non-interactive. Move the confirmation prompt to the CLI runner (`app/cli/trade.py`), allowing the Engine to remain agnostic of the environment (Test/CLI/Scheduler).

## Tech Stack
- **Python**: 3.12+
- **Database**: SQLModel (SQLite)
- **AI**: Google Gemini (via `google-genai` SDK)
- **Testing**: pytest
- **TypeCheck**: astral-ty
- **Linting**: ruff
