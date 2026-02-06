# Specification: Multi-Timeframe Trend Alignment

## Overview
This feature enhances the `MarketRegime` analysis by explicitly calculating and storing the alignment between different timeframes. By comparing the short-term trend (15m) with the long-term trend (Daily), the system can identify "Trend Confluence" (High Conviction) or "Trend Divergence" (Mean Reversion/Counter-Trend).

## Problem Statement
Currently, the LLM receives both 15m trend tables and Daily candles, but it must infer the alignment itself. Encoding this alignment into the `MarketState` data model makes it deterministic and allows for more precise strategy switching and prompt emphasizing.

## Functional Requirements
- **Data Model:** Add a `trend_alignment` field to the `MarketState` model in `app/domain/models.py`.
- **Enum Definition:** Define `TrendAlignment` enum with values: `BULLISH_CONFLUENCE`, `BEARISH_CONFLUENCE`, `DIVERGENT`.
- **Logic:** Update `MarketAnalyzer._build_market_regime` to:
    1.  Determine 15m trend (Price vs EMA20).
    2.  Determine Daily trend (Price vs Daily Open or Prev Close).
    3.  Compare them:
        -   Both Bullish -> `BULLISH_CONFLUENCE`
        -   Both Bearish -> `BEARISH_CONFLUENCE`
        -   Mismatched -> `DIVERGENT`
- **Context Injection:** Update `_format_context` to include the explicit alignment status in the prompt string.

## Non-Functional Requirements
- **Testability:** Calculation logic must be unit tested with various candle combinations.
- **Performance:** Negligible impact as it uses already-fetched data.

## Acceptance Criteria
- `MarketRegime` objects contain the correct `trend_alignment` status.
- The AI prompt explicitly states the trend alignment.
- Unit tests verify the alignment logic for all three states.
