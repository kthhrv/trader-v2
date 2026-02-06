import pytest
from app.domain.trade_actor import TradeActor

def test_trade_actor_configuration():
    """Verify that TradeActor can be initialized with configuration."""
    config = {
        "entry_price": 100.0,
        "initial_stop": 90.0,
        "atr": 5.0,
        "breakeven_r": 1.5,
        "trail_distance": 15.0,
        "direction": "BUY"
    }
    
    actor = TradeActor(trade_id="trade_1", config=config)
    
    assert actor.config["entry_price"] == 100.0
    assert actor.config["initial_stop"] == 90.0
    assert actor.config["direction"] == "BUY"
    assert actor.trade_id == "trade_1"

def test_trade_actor_default_config():
    """Verify TradeActor initializes with empty config if not provided."""
    actor = TradeActor(trade_id="trade_2")
    assert actor.config == {}
