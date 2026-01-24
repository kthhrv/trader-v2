import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.executor import TradeExecutor
from app.adapters.gemini_service import EntryType


@pytest.fixture
def mock_deps():
    mock_client = AsyncMock()
    mock_streamer = MagicMock()
    return mock_client, mock_streamer


@pytest.mark.asyncio
async def test_wait_for_trigger_respects_spread(mock_deps):
    mock_client, mock_streamer = mock_deps

    # Setup Streamer to yield 3 updates:
    # 1. Wide Spread (Offer 102 - Bid 90 = 12 > 5.0) -> SKIP
    # 2. Good Spread (Offer 100 - Bid 98 = 2 < 5.0) + Target Hit -> TRIGGER

    async def mock_stream_gen(epic):
        yield {"type": "price_update", "bid": 90.0, "offer": 102.0}  # Spread 12.0
        yield {"type": "price_update", "bid": 98.0, "offer": 100.0}  # Spread 2.0

    mock_streamer.stream = mock_stream_gen

    mock_status = MagicMock()
    executor = TradeExecutor(mock_client, mock_streamer, mock_status)

    # We want to BUY at 101.
    # Update 1: Offer 102 >= 101. BUT Spread 12 > 5. SKIP.
    # Update 2: Offer 100 < 101. Wait... (Wait, my logic is >= target entry)
    # Let's adjust target to 99 so Update 2 triggers.

    # Target 99.
    # Update 1: Offer 102 >= 99. Spread 12 > 5. SKIP.
    # Update 2: Offer 100 >= 99. Spread 2 <= 5. TRIGGER.

    result = await executor._wait_for_trigger(
        epic="CS.D.TEST.123",
        direction="BUY",
        target_entry=99.0,
        entry_type=EntryType.BREAKOUT,
        max_spread=5.0,
    )

    assert result == 100.0
