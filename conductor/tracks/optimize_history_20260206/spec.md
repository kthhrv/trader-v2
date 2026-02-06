# Specification: Optimize TradeActor History

## Overview
Currently, every price tick received by the `TradeExecutor` triggers a `TradeEvent.PRICE_UPDATED` event on the `TradeActor`. The actor appends every event to its internal `history` list, which is then serialized to JSON and saved to the database. This leads to massive database growth and performance degradation.

## Problem Statement
- **Database Bloat:** Storing every price tick in a JSON column is inefficient and unnecessary.
- **Performance:** Reading/writing large JSON blobs on every tick slows down the system.

## Proposed Solution
Modify `TradeActor.handle_event` to ignore `PRICE_UPDATED` events for the persistent history log, while still allowing the actor to react to them logic-wise (if needed, though `on_price_update` is separate).

## Key Requirements
- `TradeEvent.PRICE_UPDATED` should NOT be appended to `self.history`.
- All other events (transitions, modifications) MUST still be recorded.

## Success Criteria
- Unit tests verify `PRICE_UPDATED` is not in history.
- Existing logic remains unaffected.
