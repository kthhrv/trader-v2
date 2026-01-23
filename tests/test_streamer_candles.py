import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from app.services.streamer import StreamerService
from app.database.models import HistoricalCandle


@pytest.fixture
def mock_deps():
    mock_client = AsyncMock()
    mock_client.auth_tokens = {}
    return mock_client


@pytest.mark.asyncio
async def test_candle_aggregation(mock_deps):
    mock_client = mock_deps
    service = StreamerService(mock_client)

    # Mock database session
    mock_session = AsyncMock()
    # session.add is synchronous, so replace the auto-generated AsyncMock with MagicMock
    mock_session.add = MagicMock()

    mock_session_maker = MagicMock()
    mock_session_maker.__aenter__.return_value = mock_session

    # Mock DB save
    with patch(
        "app.services.streamer.async_session_maker", return_value=mock_session_maker
    ):
        # 1. Simulate First Tick (Minute 0, Second 10)
        t1 = datetime(2023, 1, 1, 12, 0, 10, tzinfo=timezone.utc)

        with patch("app.services.streamer.datetime") as mock_datetime:
            mock_datetime.now.return_value = t1

            # Tick 1: Bid 100
            await service._process_candle_update("TEST.EPIC", {"bid": 100.0})

            assert service.current_minute == datetime(
                2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc
            )
            assert service.current_candle is not None
            assert service.current_candle["open"] == 100.0
            assert service.current_candle["high"] == 100.0
            assert service.current_candle["low"] == 100.0
            assert service.current_candle["close"] == 100.0
            assert service.current_candle["volume"] == 1

            # Tick 2: Bid 105 (Same Minute)
            await service._process_candle_update("TEST.EPIC", {"bid": 105.0})
            assert service.current_candle is not None
            assert service.current_candle["high"] == 105.0
            assert service.current_candle["close"] == 105.0
            assert service.current_candle["volume"] == 2

            mock_session.add.assert_not_called()  # No save yet

            # Tick 3: Bid 95 (New Minute - 12:01:05)
            t2 = datetime(2023, 1, 1, 12, 1, 5, tzinfo=timezone.utc)
            mock_datetime.now.return_value = t2

            await service._process_candle_update("TEST.EPIC", {"bid": 95.0})

            # Should have saved the 12:00 candle
            assert mock_session.add.called
            saved_candle = mock_session.add.call_args[0][0]
            assert isinstance(saved_candle, HistoricalCandle)
            assert saved_candle.high == 105.0
            assert saved_candle.timestamp == datetime(
                2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc
            )

            # Current state should be reset for 12:01
            assert service.current_minute == datetime(
                2023, 1, 1, 12, 1, 0, tzinfo=timezone.utc
            )
            assert service.current_candle is not None
            assert service.current_candle["open"] == 95.0
            assert service.current_candle["volume"] == 1
