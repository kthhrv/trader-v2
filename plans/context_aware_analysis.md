# Plan: Context-Aware Analysis (V2.1)

## Goal
Enable the AI Analyst to maintain "narrative continuity" during a stalking session by feeding it the previous decisions and reasoning (Thoughts) for the same market.

## Problem
Currently, each 5-minute analysis is stateless. The AI rediscovers the same patterns (e.g., "Price is overextended") every time. It lacks memory of its own recent bias ("I am waiting for a pullback") or the failure of a previous prediction.

## Solution
Inject the last `N` (e.g., 3) analyst reports/decisions into the prompt context.

## Implementation Steps

### 1. Database Query Update
- In `app/services/trader.py` or `gemini_service.py`, add a query to fetch the last 3 rows from `trade_signals` for the current `symbol`.
- Select `timestamp`, `signal` (Action), and `reasoning` (Thoughts).

### 2. Prompt Engineering
- Modify the system prompt or user prompt in `gemini_service.py` to include a new section:
  ```text
  ## Previous Analysis Context (Last 15 Minutes)
  - [23:00] Action: WAIT. Reason: Price overextended (deviation > 1.5x ATR). Waiting for pullback to EMA20.
  - [23:05] Action: WAIT. Reason: Pullback failed. RSI oversold. Still waiting.
  ```
- Instruction: "Review your previous analysis. Maintain consistency unless market structure has fundamentally changed."

### 3. Logic Handling
- Ensure this context is passed cleanly into the `generate_trade_plan` function.

## Benefits
- **Patience:** Reinforces discipline (e.g., "As noted 5 mins ago, I am still waiting...").
- **Adaptability:** Helps the AI recognize when a predicted move (e.g., Mean Reversion) has failed vs. hasn't happened yet.
- **Human-like Reasoning:** Creates a coherent trading narrative for the session.

## Risk
- **Bias Lock:** The AI might get "stuck" in a previous bias even if data turns. We must ensure the prompt emphasizes *current data* priority.

## Timeline
- **Status:** Planned.
- **Priority:** High (Post-V2 Live Stability).
