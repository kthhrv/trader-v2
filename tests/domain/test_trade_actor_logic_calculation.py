import pytest
from app.domain.trade_actor import TradeActor, TradeState

def test_breakeven_trigger_buy():
    config = {
        "entry_price": 100.0,
        "current_stop": 90.0, # Initial stop
        "initial_stop": 90.0,
        "direction": "BUY",
        "breakeven_r": 1.5,
        "trail_distance": 15.0 # Loose trail
    }
    actor = TradeActor(trade_id="t1", config=config)
    actor.state = TradeState.OPEN
    
    # 1. Price moves to 110 (1R). No action.
    action = actor.on_price_update(110.0)
    assert action is None
    
    # 2. Price moves to 115 (1.5R). Trigger BE.
    action = actor.on_price_update(115.0)
    assert action is not None
    assert action["type"] == "MODIFY_STOP"
    assert action["new_stop"] == 100.0

def test_trailing_stop_buy():
    config = {
        "entry_price": 100.0,
        "current_stop": 100.0, # Already at BE
        "initial_stop": 90.0,
        "direction": "BUY",
        "breakeven_r": 1.5,
        "trail_distance": 5.0, # Tight trail for test
        "step_size": 0.5
    }
    actor = TradeActor(trade_id="t2", config=config)
    actor.state = TradeState.OPEN
    
    # 1. Price at 106. Trail target = 101. Stop is 100. Move to 101.
    action = actor.on_price_update(106.0)
    assert action is not None
    assert action["type"] == "MODIFY_STOP"
    assert action["new_stop"] == 101.0
    
    # Update internal state (simulating confirmation)
    actor.config["current_stop"] = 101.0
    
    # 2. Price at 106.2. Trail target = 101.2. Diff 0.2 < step 0.5. No action.
    action = actor.on_price_update(106.2)
    assert action is None
