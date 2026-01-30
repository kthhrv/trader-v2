# Plan: Market Simulator (The Matrix)

## Objective
Build a standalone tool (`scripts/market_simulator.py`) that mimics the `market-streamer` service by publishing synthetic or historical market data to Redis. This allows full-stack testing of the Sentinel, Trader, and UI during weekends or without risking capital.

## Architecture

The Simulator replaces the **Input Layer** (IG/Node.js) but keeps the **Processing Layer** (Python) intact.

```mermaid
graph LR
    A[Historical Data / Scenario] -->|Reads| B(Market Simulator)
    B -->|Publishes 'price_update'| C{Redis: market_data}
    B -->|Publishes 'candle_closed'| D{Redis: market_candles}
    C -->|Consumes| E[TradeExecutor]
    D -->|Consumes| F[Watcher/Sentinel]
    E -->|Executes (Dry Run)| G[Database/Logs]
```

## Features

1.  **Replay Mode:** Load historical candles directly from the `historical_candles` database table. Replay exact market conditions (including crashes/gaps) tick-by-tick.
2.  **Synthetic Mode (Chaos):** Generate purely random price movements (Random Walk / Geometric Brownian Motion) to simulate infinite market activity. Control volatility parameters to induce "Crashes" or "Rallies" on demand.
3.  **Tick Generation:** 
    *   *Replay:* Constrained random walk between Open/High/Low/Close of historical candles.
    *   *Synthetic:* Pure random walk.
4.  **Speed Control:** Replay at 1x, 10x, or 100x speed.

## Implementation Details

### 1. Data Sources
*   **Historical:** `trader_live` database (Table: `historical_candles`).
*   **Synthetic:** Math-based generator.

### 2. The Loop (Replay Example)
```python
# Fetch from DB
stmt = select(HistoricalCandle).where(symbol=epic).order_by(timestamp)
candles = session.exec(stmt).all()

for candle in candles:
    # 1. Publish Candle Event (Sentinel)
    publish_candle_event(candle)
    
    # 2. Fabricate Ticks (Trader)
    ticks = generate_fractal_ticks(candle.open, candle.high, candle.low, candle.close)
    for tick in ticks:
        publish_tick(tick)
        time.sleep(60 / speed / len(ticks))
```

### 3. Redis Protocol
Must match existing JSON schemas:
*   **Channel `market_data`:** `{"epic": "...", "bid": X, "offer": Y, "type": "price_update"}`
*   **Channel `market_candles`:** `{"epic": "...", "close": X, "timestamp": "...", "event": "candle_closed"}`

## Component: SimulatedIGClient (The Mock Adapter)
To test the full lifecycle without hitting IG servers, we need a mock client that mimics `AsyncIGClient`.

*   **State:** Maintains an in-memory ledger of `positions` and `balance`.
*   **Price Awareness:** Subscribes to `market_data` (Redis) to value positions in real-time.
*   **Methods:**
    *   `create_order`: Generates fake Deal ID, stores position.
    *   `close_position`: Calculates PnL based on current simulated price, updates balance.
    *   `fetch_open_positions`: Returns in-memory list.

## Execution Steps

1.  **Create Script:** `scripts/market_simulator.py` (The Data Injector).
2.  **Create Adapter:** `app/adapters/simulated_ig.py` (The Execution Mock).
3.  **Update Config:** Add `TRADING_MODE=SIMULATION` to `.env`.
4.  **Update Factory:** Modify `app/core/container.py` (or `main.py`) to inject `SimulatedIGClient` when in simulation mode.
5.  **Documentation:** Add guide on how to stop the real streamer and start the simulator.

## Benefits
*   **Weekend Dev:** Test logic changes (like V3.2 Lifecycle) without live markets.
*   **Regression Testing:** Replay "The Murder" (Friday 14:30) and verify if the new logic survives.
*   **UI Dev:** Feed data to the Dashboard to test animations/charts.
