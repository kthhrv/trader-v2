# Plan: Profit-Based Stepped Trailing Stop

**Objective:**
Optimize profit-taking by dynamically tightening the Trailing Stop distance as the trade moves deeper into profit ("Scaling Out" without closing position).

**Problem:**
The current fixed trailing stop (3.0x ATR) is great for giving a trade room to breathe initially, but it gives back too much open profit during a reversal after a strong run.
- Example: 5R profit -> Reversal -> Exit at 2R. (Giving back 3R).

**Proposed Solution:**
Implement a **Stepped Trail** logic in `TradeExecutor._monitor_position`.
As the Profit R-Multiple increases, the Trail Distance (ATR Multiplier) decreases.

**Logic Table (Example):**

| Profit Level (R) | Trail Distance | Note |
| :--- | :--- | :--- |
| < 1.5R | None | Initial Fixed Stop |
| 1.5R - 3.0R | 3.0x ATR | Standard Trail (Breakeven triggered) |
| 3.0R - 5.0R | 2.0x ATR | Tightening the noose |
| > 5.0R | 1.0x ATR | Locking in the "Home Run" |

**Implementation Details:**

1.  **Configuration:**
    - Add `stepped_trail_config` to `MARKET_CONFIGS` (or `TradeSignal`).
    - Format: `[(3.0, 2.0), (5.0, 1.0)]` -> `(Threshold_R, New_Multiplier)`.

2.  **Executor Logic (`_monitor_position`):**
    - Calculate current `Profit_R = (Current_Price - Entry) / Initial_Risk`.
    - Iterate through steps.
    - If `Profit_R > Threshold`, update `trail_distance = ATR * New_Multiplier`.
    - **Critical:** Ensure the new stop level is *closer* than the current stop. Never widen the stop.

3.  **Logging:**
    - Log "Stepped Trail Triggered: Tightening to 2.0x ATR (Profit 3.5R)".

**Benefits:**
- **Bank Wins:** Secures more profit from strong trends.
- **Flexibility:** Can be tuned per market (crypto needs loose trails, indices tighter).

**Risks:**
- **Choking:** Tightening too early might stop out a trade during a normal deep pullback before it continues to 10R.
