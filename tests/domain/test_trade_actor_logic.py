import pytest
from app.domain.trade_actor import TradeActor, TradeState, TradeEvent

def test_trade_actor_initialization():
    """Verify that a TradeActor starts in the PENDING state."""
    actor = TradeActor(trade_id="test_trade_1")
    assert actor.state == TradeState.PENDING
    assert actor.trade_id == "test_trade_1"
    assert actor.history == []

def test_transition_pending_to_open():
    """Verify transition from PENDING to OPEN on ORDER_ACKNOWLEDGED."""
    actor = TradeActor(trade_id="test_trade_1")
    actor.handle_event(TradeEvent.ORDER_ACKNOWLEDGED)
    assert actor.state == TradeState.OPEN
    assert len(actor.history) == 1
    assert actor.history[0]["event"] == TradeEvent.ORDER_ACKNOWLEDGED
    assert actor.history[0]["from_state"] == TradeState.PENDING
    assert actor.history[0]["to_state"] == TradeState.OPEN

def test_invalid_transition():
    """Verify that invalid transitions raise an error or are ignored (depending on design).
    Here we assume they raise a ValueError for strictness.
    """
    actor = TradeActor(trade_id="test_trade_1")
    # PENDING -> CLOSE_FILLED is invalid
    with pytest.raises(ValueError):
        actor.handle_event(TradeEvent.CLOSE_FILLED)

def test_transition_stop_loss_update():
    """Verify transition from OPEN to MODIFYING and back to OPEN on SL update."""
    actor = TradeActor(trade_id="test_trade_1")
    actor.handle_event(TradeEvent.ORDER_ACKNOWLEDGED)
    
    # Request update
    actor.handle_event(TradeEvent.STOP_LOSS_UPDATE_REQUESTED, payload={"new_sl": 95.0})
    assert actor.state == TradeState.MODIFYING
    
    # Confirm update
    actor.handle_event(TradeEvent.STOP_LOSS_UPDATE_CONFIRMED, payload={"confirmed_sl": 95.0})
    assert actor.state == TradeState.OPEN
    assert len(actor.history) == 3 # Ack, Request, Confirm
