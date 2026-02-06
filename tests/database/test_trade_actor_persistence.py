import pytest
from sqlmodel import select
from app.database import session as db_session
from app.database.models import TradeActorState
from app.domain.trade_actor import TradeActor, TradeState, TradeEvent

@pytest.mark.asyncio
async def test_save_and_load_trade_actor_state(test_db):
    """
    Verify that a TradeActor's state can be saved to the database 
    and then reconstructed accurately.
    """
    # 1. Create and transition an actor
    config = {"env": "prod"}
    actor = TradeActor(trade_id="trade_123", config=config)
    actor.handle_event(TradeEvent.ORDER_ACKNOWLEDGED, payload={"broker": "IG"})
    
    # 2. Save to database
    async with db_session.async_session_maker() as session:
        # We need a query function to save/upsert
        from app.database.queries import save_trade_actor_state
        await save_trade_actor_state(session, actor)
        await session.commit()
        
    # 3. Load from database
    async with db_session.async_session_maker() as session:
        from app.database.queries import load_trade_actor_state
        loaded_actor = await load_trade_actor_state(session, "trade_123")
        
    # 4. Assert equality
    assert loaded_actor is not None
    assert loaded_actor.trade_id == actor.trade_id
    assert loaded_actor.state == actor.state
    assert loaded_actor.config == config
    assert len(loaded_actor.history) == len(actor.history)
    assert loaded_actor.history[0]["event"] == TradeEvent.ORDER_ACKNOWLEDGED
    assert loaded_actor.history[0]["payload"]["broker"] == "IG"