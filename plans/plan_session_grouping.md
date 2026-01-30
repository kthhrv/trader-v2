# Plan: Trade Session Grouping (Session ID)

## Problem
1.  **Dashboard Clutter:** "Stalking" a market open generates multiple `WAIT` signals followed by a final `EXECUTED` (or `SKIPPED`). These appear as disconnected events, cluttering the UI.
2.  **Context Amnesia:** The AI doesn't know what it said 5 minutes ago. It re-analyzes the market from scratch every loop, potentially oscillating between contradictory opinions.

## Objective
Group related trading signals into a cohesive **Strategy Session** using a unique `session_id`.

## Implementation Steps

### 1. Database Schema
- **Model:** `TradeSignal`
- **Change:** Add `session_id: Optional[str] = Field(index=True)`
- **Migration:** `ALTER TABLE trade_signals ADD COLUMN session_id VARCHAR;`

### 2. Architecture Updates
- **Scheduler (`app/cli/schedule.py`):**
    - When starting a scheduled job (Stalking Loop), generate a new UUID `session_id`.
    - Pass this `session_id` to `run_market_strategy`.
- **CLI Runner (`app/cli/trade.py`):**
    - `run_market_strategy` must accept `session_id`.
    - If `session_id` is passed, it is used for the entire loop.
    - If not (e.g. manual run), generate a new one.
- **Strategy Engine (`app/services/trader.py`):**
    - `run_strategy` accepts `session_id`.
    - `generate_trade_signal` accepts `session_id`.
    - `_save_signal` persists `session_id`.

### 3. Benefits Enabled

#### A. UI Grouping (Reflex)
- The Dashboard can query: `SELECT * FROM signals GROUP BY session_id`.
- Display: One "Card" per Session.
    - **Header:** "FTSE Open (Session 123) - WIN"
    - **Body (Collapsed):** List of "WAIT" signals with timestamps.
    - **Footer:** The final Execution.

#### B. Context-Aware AI (Future V3.1)
- Before asking the AI, the Analyzer fetches previous signals:
    ```python
    history = db.query(TradeSignal).where(session_id=current_session_id).all()
    prompt += f"
PREVIOUS THOUGHTS IN THIS SESSION:
{format_history(history)}"
    ```
- This prevents the AI from flipping its bias randomly and encourages "developing a thesis."

## Execution Strategy
This is a low-risk, high-reward infrastructure change. It should be implemented before "Context Aware Analysis" as it provides the necessary linkage.
