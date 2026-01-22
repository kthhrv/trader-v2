import pytest
from unittest.mock import AsyncMock, MagicMock
from app.adapters.gemini_service import (
    GeminiService,
    TradingSignal,
    Action,
    PostMortemReport,
)


@pytest.mark.asyncio
async def test_gemini_analyze_market_success():
    service = GeminiService()
    service.client = MagicMock()

    mock_response = MagicMock()
    mock_response.text = '{"ticker": "FTSE100", "action": "BUY", "entry": 7500.0, "stop_loss": 7450.0, "size": 1.0, "atr": 20.0, "use_trailing_stop": true, "confidence": "high", "reasoning": "test"}'
    mock_response.candidates = [MagicMock(content=MagicMock(parts=[]))]

    service.client.aio = MagicMock()
    service.client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    signal = await service.analyze_market("Market Context")

    assert isinstance(signal, TradingSignal)
    assert signal.ticker == "FTSE100"
    assert signal.action == Action.BUY


@pytest.mark.asyncio
async def test_gemini_assess_news_success():
    service = GeminiService()
    service.client = MagicMock()

    mock_response = MagicMock()
    mock_response.text = '{"score": 8, "relevance": "high", "sentiment_clarity": "clear", "reasoning": "very relevant news"}'
    mock_response.candidates = [MagicMock(content=MagicMock(parts=[]))]

    service.client.aio = MagicMock()
    service.client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    news = await service.assess_news("News Text", "FTSE100")

    assert news is not None
    assert news.score == 8


@pytest.mark.asyncio
async def test_gemini_post_mortem_success():
    service = GeminiService()
    service.client = MagicMock()

    mock_response = MagicMock()
    mock_response.text = '{"did_follow_plan": true, "stop_loss_critique": "good", "slippage_impact": "low", "reasoning_quality": "sound", "key_lesson": "none", "verdict": "pass"}'
    mock_response.candidates = [MagicMock(content=MagicMock(parts=[]))]

    service.client.aio = MagicMock()
    service.client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    report = await service.generate_post_mortem({"entry": 100}, {"pnl": 50})

    assert isinstance(report, PostMortemReport)
    assert report.did_follow_plan is True
    assert report.verdict == "pass"
