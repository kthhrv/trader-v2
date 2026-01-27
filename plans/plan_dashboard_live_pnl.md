# Plan: Near-Live PnL in Dashboard

**Objective:**
Display unrealized Profit/Loss for **OPEN** positions in the Reflex Dashboard's "Activity Log".

**Current State:**
- The `Activity Log` table shows `pnl` only for closed trades.
- For open trades, `pnl` is displayed as `£0.00` or `None`.
- The dashboard refreshes data periodically (or on manual refresh).

**Data Source Strategy:**
We will use the **Latest Historical Candle** from the database as a proxy for "Current Price".
- **Pros:** Efficient (no external API calls), reuses existing DB connection.
- **Cons:** 1-minute latency (since `CandleBuilder` writes to DB on minute close).
- **Verdict:** Acceptable for a dashboard "Activity Log". Real-time tick streaming is overkill for this view.

---

## Implementation Steps

### 1. Update Database Queries (`app/database/queries.py`)
- Add a helper function `get_latest_price(symbol: str) -> float`.
    - Query `HistoricalCandle` table.
    - Order by `timestamp DESC`.
    - Limit 1.
    - Return `close` price.

### 2. Update Dashboard Logic (`dashboard/dashboard/dashboard.py`)
- Modify `load_data` (specifically the loop processing `raw_activity`).
- Identify **OPEN** trades (`execution.outcome_status == "OPEN"`).
- For each open trade:
    - Call `get_latest_price(symbol)`.
    - Calculate PnL:
        - **BUY:** `(Current - Entry) * Size`
        - **SELL:** `(Entry - Current) * Size`
    - Update the `pnl` string in the dashboard dictionary (`f"£{pnl:.2f}"`).
    - Optionally: Add a visual indicator (e.g., `(Open) £50.20` or color-code green/red).

### 3. UI Refinement
- Ensure the `pnl` column sorts correctly (might require raw float value in data structure alongside formatted string).
- Add color logic:
    - **Green:** PnL > 0
    - **Red:** PnL < 0
    - **Gray:** Closed/Zero.

## Estimated Effort
- **Low (1-2 hours).**
- Logic is straightforward.
- Dependency: `get_latest_price` implementation.

## Code Snippet (Preview)

```python
# app/database/queries.py
async def get_latest_price(session, symbol: str) -> Optional[float]:
    stmt = select(HistoricalCandle.close).where(
        HistoricalCandle.symbol == symbol
    ).order_by(desc(HistoricalCandle.timestamp)).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()
```

```python
# dashboard.py
if execution.outcome_status == "OPEN":
    latest_price = await get_latest_price(session, symbol)
    if latest_price:
        diff = latest_price - execution.fill_price
        if execution.direction == "SELL": diff = -diff
        unrealized = diff * execution.size
        item["pnl"] = f"£{unrealized:.2f}"
```
