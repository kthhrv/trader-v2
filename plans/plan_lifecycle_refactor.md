# Plan: Lifecycle & Event Stream Refactor

## Problem
The current `TradeExecutor` logic (`_wait_for_trigger` and `_monitor_position`) relies on linear loops that only listen to price updates from the `market_data` Redis channel.
- **Limitation:** These loops are "deaf" to external signals (Sentinel Triggers, Manual Cancels) once started.
- **Risk:** We cannot implement "Active Risk Management" (e.g., Sentinel Kill Switch) without hacking specific checks into every loop iteration.

## Objective
Refactor the `StreamerService` to act as a **Unified Event Bus** that yields both Market Data and Control Signals. This allows trading loops to react instantly to regime changes or commands.

## Architecture

### 1. Unified Streamer
Modify `StreamerService.stream(epic)` to subscribe to multiple Redis channels:
*   `market_data`: Real-time prices (Existing).
*   `trade_commands`: Control signals (Sentinel triggers, Manual overrides).

### 2. Event Model (Strictly Typed)
Use Pydantic models (discriminated union) to ensure type safety within the handling loops.

```python
class EventType(str, Enum):
    PRICE = "PRICE"
    SENTINEL = "SENTINEL"
    COMMAND = "COMMAND"

class BaseEvent(BaseModel):
    timestamp: datetime
    epic: str

class PriceEvent(BaseEvent):
    type: Literal[EventType.PRICE] = EventType.PRICE
    bid: float
    offer: float

class SentinelEvent(BaseEvent):
    type: Literal[EventType.SENTINEL] = EventType.SENTINEL
    trigger: str
    severity: str # "HIGH", "MEDIUM"

class CommandEvent(BaseEvent):
    type: Literal[EventType.COMMAND] = EventType.COMMAND
    action: str # "CANCEL", "FORCE_EXIT"

# Union Type for easy parsing
TraderEvent = Union[PriceEvent, SentinelEvent, CommandEvent]
```

### 3. Loop Logic Updates
Update `TradeExecutor` methods to handle typed events:

*   **`_wait_for_trigger` (Stalking):**
    *   `if isinstance(event, SentinelEvent)` AND `direction != signal.direction`: **ABORT**.
    *   If `type == COMMAND` AND `action == CANCEL`: **ABORT**.

*   **`_monitor_position` (Live):**
    *   If `type == SENTINEL` AND `severity == HIGH`: **TIGHTEN_STOP**.
    *   If `type == COMMAND` AND `action == FORCE_EXIT`: **CLOSE_POSITION**.

## Implementation Steps

1.  **Refactor StreamerService:**
    *   Update `subscribe` call to include `trade_commands`.
    *   Normalize `message` payload before yielding.

2.  **Refactor Executor:**
    *   Update `_wait_for_trigger` to process non-price events.
    *   Update `_monitor_position` to process non-price events.

3.  **Validation:**
    *   Test that a "fake" Sentinel message sent to Redis correctly terminates a `_wait_for_trigger` loop.

## Outcome
A reactive, interruptible trading engine that serves as the foundation for V3.2 Active Management features.
