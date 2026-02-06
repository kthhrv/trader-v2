import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.executor import TradeExecutor
from app.domain.trade_actor import TradeState, TradeEvent
from app.adapters.gemini_service import Action, EntryType

@pytest.fixture
def mock_deps():
    mock_client = AsyncMock()
    mock_streamer = MagicMock()
    mock_streamer.stop = AsyncMock()
    mock_status = MagicMock()
    return mock_client, mock_streamer, mock_status

@pytest.mark.asyncio
async def test_executor_updates_actor_state(mock_deps):
    mock_client, mock_streamer, mock_status = mock_deps
    
    # Mock IG response
    mock_client.create_order.return_value = {"dealId": "DEAL1", "level": 100.0}
    mock_client.fetch_deal_confirmation.return_value = {"dealStatus": "ACCEPTED", "dealId": "DEAL1"}
    
    executor = TradeExecutor(mock_client, mock_streamer, mock_status)
    executor._save_execution = AsyncMock()
    executor._monitor_position = AsyncMock()
    
    # Mock signal
    signal = MagicMock()
    signal.action = Action.BUY
    signal.entry_type = EntryType.INSTANT
    signal.entry = 100.0
    signal.size = 1.0
    signal.stop_loss = 90.0
    signal.take_profit = 110.0
    signal.use_trailing_stop = False
    
    with patch("app.services.executor.save_trade_actor_state", new_callable=AsyncMock) as mock_save:
        await executor.execute_trade(signal, "EPIC1", 123)
        
        # Verify save_trade_actor_state was called
        assert mock_save.call_count >= 1
        # The last call should have the actor in OPEN state
        args, kwargs = mock_save.call_args
        actor = args[1]
        assert actor.state == TradeState.OPEN
        assert actor.trade_id == "DEAL1"

@pytest.mark.asyncio
async def test_monitor_position_updates_actor(mock_deps):
    mock_client, mock_streamer, mock_status = mock_deps
    
    # 1. Setup Stream
    async def mock_stream(epic):
        # Trigger BE then trailing
        yield {"type": "price_update", "bid": 120.0, "offer": 122.0}

    mock_streamer.stream = mock_stream
    mock_status.get_market_close_datetime.return_value = None
    
    executor = TradeExecutor(mock_client, mock_streamer, mock_status)
    executor._is_position_open = AsyncMock(return_value=True)
    executor._update_execution_stop = AsyncMock()
    
    # 2. Mock Actor Loading/Saving
    from app.domain.trade_actor import TradeActor, TradeState
    initial_actor = TradeActor(trade_id="DEAL123")
    initial_actor.state = TradeState.OPEN
    
    with patch("app.services.executor.load_trade_actor_state", return_value=initial_actor) as mock_load, \
         patch("app.services.executor.save_trade_actor_state", new_callable=AsyncMock) as mock_save, \
         patch("app.services.executor.datetime") as mock_dt:
        
        import itertools
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).timestamp()
        mock_dt.now.return_value.timestamp.side_effect = itertools.count(ts, 10.0)
        mock_dt.now.return_value.tzinfo = timezone.utc
        
        await executor._monitor_position(
            deal_id="DEAL123",
            epic="TEST",
            direction="BUY",
            entry_price=100.0,
            current_stop=90.0,
            atr=5.0,
            size=1.0,
        )
        
        # 3. Verify actor was updated
        # It should have: PRICE_UPDATED, STOP_LOSS_UPDATE_REQUESTED, STOP_LOSS_UPDATE_CONFIRMED
        assert mock_save.call_count >= 1
        # Check that at least one call saved an actor that went through MODIFYING
        found_modifying = False
        for call in mock_save.call_args_list:
            saved_actor = call.args[1]
            if any(h["event"] == TradeEvent.STOP_LOSS_UPDATE_REQUESTED for h in saved_actor.history):
                found_modifying = True
        
        assert found_modifying, "Actor did not record STOP_LOSS_UPDATE_REQUESTED"
