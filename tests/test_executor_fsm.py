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
