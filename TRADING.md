# A Day in the Life of Trader V2

This document illustrates how the bot navigates a trading day, switching strategies and reacting to events in real-time.

---

## 🌅 07:30 UTC: Pre-Game (Stalking)
**Context:** London Open is 30 minutes away.
*   **Action:** The Scheduler (or Stalking Logic) begins monitoring `FTSE 100`.
*   **State:** The bot is **Passive**. It records candles via `market-streamer` but does not trade yet unless a massive macro event occurs.

---

## 🔔 07:55 UTC: The Open (Regime Bypass)
**Context:** 5 minutes before official open.
*   **Trigger:** Scheduled Job `RUN_STRATEGY` for `ftse`.
*   **Logic:**
    *   **Time Check:** Is it < 30 mins since open? **YES**.
    *   **Decision:** **IGNORE ADX**. Force Default Strategy (`momentum_breakout`).
*   **Why?** The Open is chaotic. Indicators like ADX (lagging) are useless here. We want to catch the initial "Drive".
*   **Execution:**
    *   AI sees price breaking pre-market high.
    *   Signal: `BUY STOP @ 8250` (`EntryType.BREAKOUT`).

---

## 📉 10:30 UTC: The Mid-Morning Lull (Regime Active)
**Context:** The initial rush is over. Volume fades.
*   **Trigger:** Scheduled Job (or Watcher Loop).
*   **Logic:**
    *   **Time Check:** Is it < 30 mins since open? **NO**.
    *   **Regime Check:** Calculate ADX(14) and Volatility Ratio.
        *   Result: `ADX = 14` (Weak Trend), `VolRatio = 0.7` (Compression).
    *   **Decision:** Switch to `mean_reversion`.
*   **Why?** The market is chopping. Trend following will lose money here. We want to fade the edges.
*   **Execution:**
    *   AI sees price hitting the Upper Bollinger Band.
    *   Signal: `SELL LIMIT @ 8280` (`EntryType.PULLBACK`).

---

## ⚡ 13:30 UTC: US CPI Data (The Reflex)
**Context:** US Inflation data drops. Massive spike.
*   **Trigger:** `WatcherService` (PriceSensor) detects `FTSE` moved +0.25% in 15 seconds.
*   **Logic:**
    *   **Command:** `RUN_STRATEGY` with `override_strategy="volatility_response"`.
    *   **Regime Check:** **SKIPPED** (Override takes precedence).
*   **Why?** We don't have time to analyze ADX. The market is moving NOW.
*   **Execution:**
    *   AI validates the 1-minute candle volume is huge (Legit move).
    *   Signal: `BUY MARKET` (`EntryType.INSTANT`).
    *   **Result:** We catch the impulse move up.

---

## 🏛 14:30 UTC: US Open (The Trap)
**Context:** S&P 500 Opens.
*   **Trigger:** Scheduled Job for `spx`.
*   **Logic:**
    *   **Time Check:** Market Open Phase.
    *   **Default Strategy:** `us_volatility` (Configured in `MARKET_CONFIGS`).
*   **Why?** The US Open is famous for "Fake-outs" (Liquidity Traps).
*   **Execution:**
    *   Price breaks high but volume is weak.
    *   AI Signal: `SELL STOP` below the range (Fading the breakout).

---

## 🌙 22:00 UTC: The Close
*   **Action:** `Executor` checks for `force_close_at_market_close` settings.
*   **Result:** Any open intraday positions are closed to avoid overnight gap risk.
*   **Logs:** `TradeSignal` recorded in DB.