import pytest
from app.domain.trade_actor import TradeActor, TradeEvent, TradeState

def test_history_optimization_skips_price_updates():
    """Verify that PRICE_UPDATED events are not appended to history."""
    actor = TradeActor(trade_id="test_opt")
    actor.state = TradeState.OPEN
    
    # 1. Trigger PRICE_UPDATED
    actor.handle_event(TradeEvent.PRICE_UPDATED, payload={"bid": 100, "offer": 101})
    
    # 2. Verify history is empty (or doesn't contain this event)
    assert len(actor.history) == 0
    
    # 3. Trigger other event
    actor.handle_event(TradeEvent.STOP_LOSS_UPDATE_REQUESTED, payload={"new_stop": 90})
    
    # 4. Verify history contains other event
    assert len(actor.history) == 1
    assert actor.history[0]["event"] == TradeEvent.STOP_LOSS_UPDATE_REQUESTED
