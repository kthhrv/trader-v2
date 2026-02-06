from enum import Enum
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

class TradeState(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    MODIFYING = "MODIFYING"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"

class TradeEvent(str, Enum):
    ORDER_SENT = "ORDER_SENT"
    ORDER_ACKNOWLEDGED = "ORDER_ACKNOWLEDGED"
    PRICE_UPDATED = "PRICE_UPDATED"
    MANUAL_CLOSE_REQUESTED = "MANUAL_CLOSE_REQUESTED"
    STOP_LOSS_TRIGGERED = "STOP_LOSS_TRIGGERED"
    TAKE_PROFIT_TRIGGERED = "TAKE_PROFIT_TRIGGERED"
    STOP_LOSS_UPDATE_REQUESTED = "STOP_LOSS_UPDATE_REQUESTED"
    STOP_LOSS_UPDATE_CONFIRMED = "STOP_LOSS_UPDATE_CONFIRMED"
    CLOSE_FILLED = "CLOSE_FILLED"

class TradeActor:
    def __init__(self, trade_id: str, config: Dict[str, Any] = None):
        self.trade_id = trade_id
        self.config = config or {}
        self.state = TradeState.PENDING
        self.history: List[Dict[str, Any]] = []
        
        # Define allowed transitions: {CurrentState: {Event: NewState}}
        self._transitions = {
            TradeState.PENDING: {
                TradeEvent.ORDER_ACKNOWLEDGED: TradeState.OPEN,
                TradeEvent.ORDER_SENT: TradeState.PENDING, # Idempotent-ish
            },
            TradeState.OPEN: {
                TradeEvent.PRICE_UPDATED: TradeState.OPEN, # Stay open
                TradeEvent.MANUAL_CLOSE_REQUESTED: TradeState.CLOSING,
                TradeEvent.STOP_LOSS_TRIGGERED: TradeState.CLOSING,
                TradeEvent.TAKE_PROFIT_TRIGGERED: TradeState.CLOSING,
                TradeEvent.STOP_LOSS_UPDATE_REQUESTED: TradeState.MODIFYING,
                TradeEvent.CLOSE_FILLED: TradeState.CLOSED, # Direct close? Maybe unlikely without CLOSING first, but possible
            },
            TradeState.MODIFYING: {
                TradeEvent.STOP_LOSS_UPDATE_CONFIRMED: TradeState.OPEN,
                TradeEvent.PRICE_UPDATED: TradeState.MODIFYING, # Can still get price updates
                TradeEvent.STOP_LOSS_TRIGGERED: TradeState.CLOSING, # Can still trigger SL while modifying?
            },
            TradeState.CLOSING: {
                TradeEvent.CLOSE_FILLED: TradeState.CLOSED,
            },
            TradeState.CLOSED: {
                # No transitions from CLOSED
            }
        }

    def on_price_update(self, current_price: float) -> Optional[Dict[str, Any]]:
        """
        Calculates if any action is needed based on the new price.
        Returns a dict describing the action (e.g. {"type": "MODIFY_STOP", "new_stop": ...})
        or None if no action is needed.
        """
        if self.state != TradeState.OPEN:
            return None

        cfg = self.config
        direction = cfg.get("direction")
        entry_price = cfg.get("entry_price")
        current_stop = cfg.get("current_stop")
        initial_stop = cfg.get("initial_stop")
        
        if not all([direction, entry_price, current_stop, initial_stop]):
            return None

        risk_distance = abs(entry_price - initial_stop)
        breakeven_r = cfg.get("breakeven_r", 1.5)
        trail_distance = cfg.get("trail_distance")
        step_size = cfg.get("step_size", 0.1)

        # Logic State
        moved_to_breakeven = False
        if direction == "BUY":
            moved_to_breakeven = current_stop >= entry_price
        else:
            moved_to_breakeven = current_stop <= entry_price

        target_stop = None

        # Rule 1: Check for Breakeven Trigger
        is_be_triggered = False
        if not moved_to_breakeven and risk_distance > 0:
            profit_dist = (current_price - entry_price) if direction == "BUY" else (entry_price - current_price)
            if profit_dist >= (breakeven_r * risk_distance):
                target_stop = entry_price
                is_be_triggered = True

        # Rule 2: Dynamic Trailing (If already at BE OR triggered now)
        if (moved_to_breakeven or is_be_triggered) and trail_distance:
            trail_target = None
            if direction == "BUY":
                trail_target = round(current_price - trail_distance, 1)
            elif direction == "SELL":
                trail_target = round(current_price + trail_distance, 1)

            if trail_target:
                # Comparison basis is either the new BE stop or the existing stop
                basis_stop = target_stop if target_stop is not None else current_stop
                
                is_improvement = False
                if direction == "BUY":
                    is_improvement = trail_target > (basis_stop + step_size)
                else:
                    is_improvement = trail_target < (basis_stop - step_size)
                
                if is_improvement:
                    target_stop = trail_target

        if target_stop is not None:
             return {"type": "MODIFY_STOP", "new_stop": target_stop}

        return None

    def handle_event(self, event: TradeEvent, payload: Dict[str, Any] = None) -> None:
        """
        Process an event and transition state if valid.
        """
        if event not in self._transitions.get(self.state, {}):
            raise ValueError(f"Invalid transition: Cannot handle event {event} from state {self.state}")
            
        new_state = self._transitions[self.state][event]
        
        # Record transition
        # Optimization: Do NOT record PRICE_UPDATED events in history to prevent DB bloat
        if event != TradeEvent.PRICE_UPDATED:
            transition_record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": event,
                "from_state": self.state,
                "to_state": new_state,
                "payload": payload or {}
            }
            self.history.append(transition_record)
        
        # Update state
        self.state = new_state