import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta
import json

from app.services.watcher import MetricSensor
from app.services.command_listener import CommandListener
from app.services.trader import StrategyEngine
from app.domain.models import (
    MarketRegime,
    MarketIndicators,
    MarketState,
    VolatilityRegime,
    TrendContext,
)
import app.services.watcher as watcher_module
import app.services.trader as trader_module


# --- Mock Data Helper ---
def create_parabolic_candles(epic, start_time, count=25):
    """
    Generates a sequence of candles that ends in a Parabolic state.
    """
    candles = []
    # Start flat-ish
    price = 100.0
    for i in range(count):
        # Last 5 candles go parabolic (spike 10 points when ATR is ~1)
        if i >= count - 5:
            price += 2.0
        else:
            price += 0.1

        data = {
            "epic": epic,
            "timestamp": (start_time + timedelta(minutes=i)).isoformat(),
            "open": price - 0.1,
            "high": price + 0.1,
            "low": price - 0.1,
            "close": price,
            "volume": 1000 + (i * 100),  # Increasing volume
        }
        candles.append(data)
    return candles


# --- Test ---
@pytest.mark.asyncio
async def test_sentinel_to_strategy_e2e(monkeypatch):
    # Patch MARKET_CONFIGS in both modules to recognize the test epic
    test_configs = {
        "test_market": {
            "epic": "TEST.EPIC",
            "name": "Test Market",
            "max_spread": 2.0,
            "strategy_id": "momentum_breakout",
        }
    }
    monkeypatch.setattr(watcher_module, "MARKET_CONFIGS", test_configs)
    monkeypatch.setattr(trader_module, "MARKET_CONFIGS", test_configs)

    # Patch MarketStatusService to always return open for Sentinel
    monkeypatch.setattr(
        watcher_module.MarketStatusService, "is_market_open", lambda self, epic: True
    )

    # 1. Setup Watcher (MetricSensor)
    mock_notifier = AsyncMock()
    sensor = MetricSensor(mock_notifier)
    sensor.redis_client = AsyncMock()  # Mock Redis to capture publish

    # 2. Setup Trader (CommandListener -> Engine)
    mock_analyzer = MagicMock()
    mock_risk = MagicMock()
    mock_executor = MagicMock()
    mock_status = MagicMock()

    # Configure Engine to accept the run
    mock_status.is_holiday.return_value = False

    # Important: The Analyzer needs to "see" the same parabolic state
    # that the Sentinel saw. In a real system, they both read from DB/Redis.
    # Here, we mock the Analyzer to return a Parabolic Regime when called.
    mock_regime = MarketRegime(
        symbol="TEST.EPIC",
        timestamp=datetime.now(timezone.utc),
        current_price=150.0,
        daily_open=100.0,
        prev_close=100.0,
        gap_percent=0.0,
        indicators=MarketIndicators(
            atr_14=1.0,
            avg_atr=1.0,
            rsi_14=85.0,
            adx_14=50.0,
            ema_20=140.0,
            rvol=2.5,
            ema_slope=1.0,
            extension_factor=10.0,  # Extreme Parabolic
        ),
        state=MarketState(
            trend=TrendContext.BULLISH,
            volatility=VolatilityRegime.HIGH,
            volatility_ratio=2.0,
            is_parabolic=True,  # <--- The Key
            is_choppy=False,
        ),
    )

    # Let's mock the analyzer to just return a dummy signal,
    # but we will spy on the strategy_id passed to it.
    mock_analyzer.analyze_market = AsyncMock(return_value=MagicMock(action="SELL"))

    engine = StrategyEngine(mock_analyzer, mock_risk, mock_executor, mock_status)
    listener = CommandListener(engine)

    # 3. Simulate Data Flow (Watcher)
    epic = "TEST.EPIC"
    start_time = datetime.now(timezone.utc)
    candles = create_parabolic_candles(epic, start_time)

    # Feed candles to Sensor
    for c in candles:
        await sensor.on_candle(c)

    # 4. Verify Watcher Triggered
    sensor.redis_client.publish.assert_called()
    call_args = sensor.redis_client.publish.call_args_list[-1]  # Last call
    channel = call_args[0][0]
    payload_str = call_args[0][1]
    payload = json.loads(payload_str)

    assert channel == "trade_commands"
    assert payload["command"] == "RUN_STRATEGY"
    assert "PARABOLIC_EXT" in payload["reason"]

    print(f"\n[Watcher] Triggered: {payload}")

    # 5. Bridge: Pass payload to Listener (Simulating Redis Pub/Sub)
    # The listener should call engine.run_strategy
    # Note: We need to mock _save_signal in engine to avoid DB calls
    engine._save_signal = AsyncMock(return_value=MagicMock(id=1))  # type: ignore

    await listener.handle_command(payload)

    # 6. Verify Trader Execution
    # Check that analyze_market was called
    mock_analyzer.analyze_market.assert_called_once()

    # Ideally, we'd use a real MarketAnalyzer here with the mock data to prove
    # the whole chain works. Let's do that!

    # --- Real Analyzer Setup ---
    from app.services.analyzer import MarketAnalyzer

    real_analyzer = MarketAnalyzer(
        market_data=MagicMock(),  # Mocks data fetching
        news_client=MagicMock(),
        gemini=MagicMock(),
    )
    # Mock internal build_regime to return our parabolic regime
    real_analyzer._build_market_regime = AsyncMock(return_value=mock_regime)  # type: ignore
    real_analyzer.news_client.fetch_news = AsyncMock(return_value="News")  # type: ignore

    mock_gemini_analyze = AsyncMock(return_value=MagicMock(action="SELL"))
    real_analyzer.gemini.analyze_market = mock_gemini_analyze  # type: ignore

    # Re-create engine with REAL Analyzer

    engine_v2 = StrategyEngine(real_analyzer, mock_risk, mock_executor, mock_status)
    engine_v2._save_signal = AsyncMock(return_value=MagicMock(id=1))  # type: ignore
    listener_v2 = CommandListener(engine_v2)

    # Handle the command again
    await listener_v2.handle_command(payload)

    # 7. Final Verification
    # The Gemini service should have been called with the CLIMAX prompt.
    call_args = real_analyzer.gemini.analyze_market.call_args
    prompt_used = call_args[0][1]  # 2nd arg is instruction

    assert "Contrarian Specialist" in prompt_used  # Phrase from STRAT_CLIMAX_REVERSAL
    assert "Parabolic Market Event" in prompt_used

    print(
        "\n[Trader] Successfully selected 'climax_reversal' strategy based on Regime."
    )
