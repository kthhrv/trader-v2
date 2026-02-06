import pytest
from app.domain.trade_actor import TradeState, TradeEvent

def test_trade_states_exist():
    """Verify that all required trade states are defined."""
    assert TradeState.PENDING.value == "PENDING"
    assert TradeState.OPEN.value == "OPEN"
    assert TradeState.MODIFYING.value == "MODIFYING"
    assert TradeState.CLOSING.value == "CLOSING"
    assert TradeState.CLOSED.value == "CLOSED"

def test_trade_events_exist():
    """Verify that all required trade events are defined."""
    assert TradeEvent.ORDER_SENT.value == "ORDER_SENT"
    assert TradeEvent.ORDER_ACKNOWLEDGED.value == "ORDER_ACKNOWLEDGED"
    assert TradeEvent.PRICE_UPDATED.value == "PRICE_UPDATED"
    assert TradeEvent.MANUAL_CLOSE_REQUESTED.value == "MANUAL_CLOSE_REQUESTED"
    assert TradeEvent.STOP_LOSS_TRIGGERED.value == "STOP_LOSS_TRIGGERED"
    assert TradeEvent.TAKE_PROFIT_TRIGGERED.value == "TAKE_PROFIT_TRIGGERED"
    assert TradeEvent.CLOSE_FILLED.value == "CLOSE_FILLED"
