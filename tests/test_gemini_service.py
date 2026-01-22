import pytest
from unittest.mock import AsyncMock, MagicMock
from app.adapters.gemini_service import GeminiService, TradingSignal, Action


@pytest.mark.asyncio
async def test_gemini_analyze_market_success():
    # Setup mock
    service = GeminiService()
    service.client = MagicMock()

    mock_response = MagicMock()
    mock_response.text = '{"ticker": "FTSE100", "action": "BUY", "entry": 7500.0, "stop_loss": 7450.0, "size": 1.0, "atr": 20.0, "use_trailing_stop": true, "confidence": "high", "reasoning": "test"}'
    mock_response.candidates = [MagicMock(content=MagicMock(parts=[]))]

    # Mock the aio client
    service.client.aio = MagicMock()
    service.client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    signal = await service.analyze_market("Market Context")

    assert isinstance(signal, TradingSignal)
    assert signal.ticker == "FTSE100"
    assert signal.action == Action.BUY
    assert signal.entry == 7500.0


@pytest.mark.asyncio
async def test_gemini_assess_news_success():
    service = GeminiService()
    service.client = MagicMock()

    mock_response = MagicMock()
    mock_response.text = '{"score": 8, "relevance": "high", "sentiment_clarity": "clear", "reasoning": "very relevant news"}'

    service.client.aio = MagicMock()
    service.client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    news = await service.assess_news("News Text", "FTSE100")

    assert news is not None
    assert news.score == 8
    assert news.relevance == "high"
