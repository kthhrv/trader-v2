from enum import Enum
from typing import List, Dict, Any
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
    def __init__(self, trade_id: str):
        self.trade_id = trade_id
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

    def handle_event(self, event: TradeEvent, payload: Dict[str, Any] = None) -> None:
        """
        Process an event and transition state if valid.
        """
        if event not in self._transitions.get(self.state, {}):
            raise ValueError(f"Invalid transition: Cannot handle event {event} from state {self.state}")
            
        new_state = self._transitions[self.state][event]
        
        # Record transition
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