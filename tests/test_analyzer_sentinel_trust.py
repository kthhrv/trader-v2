import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.analyzer import MarketAnalyzer


@pytest.mark.asyncio
async def test_analyzer_trusts_sentinel_parabolic():
    # Setup Mocks
    market_data = AsyncMock()
    news_client = AsyncMock()
    gemini = AsyncMock()

    analyzer = MarketAnalyzer(market_data, news_client, gemini)

    # Mock calm 15m data (extension < 2.5)
    import datetime

    mock_candles = []
    for i in range(50):
        candle = MagicMock()
        candle.close = 100.5
        candle.open = 100.0
        candle.timestamp = datetime.datetime.now() - datetime.timedelta(minutes=15 * i)
        candle.model_dump.return_value = {
            "timestamp": candle.timestamp,
            "open": candle.open,
            "high": 101.0,
            "low": 99.0,
            "close": candle.close,
            "volume": 1000,
        }
        mock_candles.append(candle)

    market_data.get_latest_candles.return_value = mock_candles
    market_data.get_vix_level.return_value = 20.0
    market_data.get_client_sentiment.return_value = {"long": 50, "short": 50}

    # Mock daily candles for gap calculation
    daily_candle = MagicMock()
    daily_candle.close = 100.0
    daily_candle.open = 100.0
    daily_candle.timestamp = datetime.datetime.now()
    market_data.get_latest_candles.side_effect = (
        lambda epic, tf, limit: mock_candles
        if tf != "DAY"
        else [daily_candle, daily_candle]
    )

    config = {"epic": "TEST.EPIC", "strategy_id": "momentum_breakout"}

    # 1. Test WITHOUT sentinel (should be normal/momentum)
    regime_normal = await analyzer._build_market_regime(
        "TEST.EPIC", trigger_source="scheduler"
    )
    assert regime_normal is not None
    assert regime_normal.state.is_parabolic is False

    # 2. Test WITH sentinel PARABOLIC (should force True)
    regime_forced = await analyzer._build_market_regime(
        "TEST.EPIC", trigger_source="sentinel_PARABOLIC_EXT_3.0x"
    )
    assert regime_forced is not None
    assert regime_forced.state.is_parabolic is True
    assert abs(regime_forced.indicators.extension_factor) >= 2.5

    # 3. Test Strategy Selection with forced parabolic
    news_client.fetch_news.return_value = "No news"

    # In determine_strategy, it should pick climax_reversal
    strat = analyzer._determine_strategy(regime_forced, "momentum_breakout", config)
    assert strat == "climax_reversal"
