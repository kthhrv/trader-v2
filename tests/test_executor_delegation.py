import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.executor import TradeExecutor
from app.domain.trade_actor import TradeState, TradeEvent

@pytest.fixture
def mock_deps():
    mock_client = AsyncMock()
    mock_streamer = MagicMock()
    mock_streamer.stop = AsyncMock()
    mock_status = MagicMock()
    return mock_client, mock_streamer, mock_status

@pytest.mark.asyncio
async def test_executor_delegates_to_actor(mock_deps):
    mock_client, mock_streamer, mock_status = mock_deps
    
    # 1. Setup Stream (just one tick)
    async def mock_stream(epic):
        yield {"type": "price_update", "bid": 120.0, "offer": 122.0}

    mock_streamer.stream = mock_stream
    mock_status.get_market_close_datetime.return_value = None
    
    executor = TradeExecutor(mock_client, mock_streamer, mock_status)
    executor._is_position_open = AsyncMock(return_value=True)
    executor._update_stop_loss = AsyncMock()
    
    # 2. Mock Actor with specific instruction
    mock_actor = MagicMock()
    mock_actor.state = TradeState.OPEN
    mock_actor.on_price_update.return_value = {"type": "MODIFY_STOP", "new_stop": 105.0}
    
    with patch("app.services.executor.load_trade_actor_state", return_value=mock_actor), \
         patch("app.services.executor.save_trade_actor_state", new_callable=AsyncMock), \
         patch("app.services.executor.datetime") as mock_dt:
        
        from datetime import datetime, timezone
        # Use a real datetime object and mock its methods
        fixed_now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = fixed_now
        
        await executor._monitor_position(
            deal_id="DEAL123",
            epic="TEST",
            direction="BUY",
            entry_price=100.0,
            current_stop=90.0,
            atr=5.0,
            size=1.0,
        )
        
        # 3. Verify actor.on_price_update was called
        mock_actor.on_price_update.assert_called()
        
        # 4. Verify executor acted on the instruction
        executor._update_stop_loss.assert_called_with("DEAL123", 105.0, actor=mock_actor)