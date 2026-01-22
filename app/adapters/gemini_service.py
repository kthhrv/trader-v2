import json
from enum import Enum
from typing import Optional

from google import genai
from google.genai import types, errors
from pydantic import BaseModel, Field
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from app.core.config import settings
from app.core.logger import logger


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    WAIT = "WAIT"
    ERROR = "ERROR"


class EntryType(str, Enum):
    INSTANT = "INSTANT"


class NewsQuality(BaseModel):
    score: int = Field(description="Quality score from 0 to 10.")
    relevance: str = Field(description="Relevance to the specific market.")
    sentiment_clarity: str = Field(description="Clarity of sentiment.")
    reasoning: str = Field(description="Explanation of the score.")


class TradingSignal(BaseModel):
    ticker: str
    action: Action
    entry: float
    entry_type: EntryType = EntryType.INSTANT
    stop_loss: float
    take_profit: Optional[float] = None
    size: float
    atr: float
    use_trailing_stop: bool
    confidence: str
    reasoning: str


class GeminiService:
    """
    Async service for Gemini AI analysis.
    Uses structured outputs and thinking (Reasoning) models.
    """

    def __init__(self, model_name: str = "gemini-2.0-flash-thinking-exp-01-21"):
        self.model_name = model_name
        # Note: genai.Client can be used for async if we use its async methods
        # However, the SDK also supports a global async client approach or individual calls.
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY.get_secret_value())

        self.system_instruction = """
            You are a Senior Momentum Trader specializing in "Open Drive" breakout strategies for global indices.
            Your objective is to identify high-probability breakout setups during the market open (first 90 mins).

            ### 1. Market Analysis Protocol
            Analyze provided Market Context and News to determine Market Regime:
            - **High Volatility (ATR > Avg):** Favor BREAKOUTS.
            - **Low Volatility (ATR < Avg):** Favor MEAN REVERSION or WAIT.
            
            ### 2. Trading Rules (Strict)
            - **Extension Rule:** Do NOT enter if entry > 1.5x ATR from EMA20.
            - **Stop Loss:** MUST be at least 1.5x ATR away from entry.
            - **High Volatility Stop:** Increase to 2.0x ATR.
            - **Trailing Stop:** use_trailing_stop=True for Trend Days, False for Range Days.
        """

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((errors.ServerError, errors.APIError)),
    )
    async def analyze_market(
        self, market_context: str, strategy_name: str = "Market Open"
    ) -> Optional[TradingSignal]:
        """
        Analyzes market data and returns a structured TradingSignal.
        """
        prompt = f"""Analyze the following {strategy_name} market data and generate a trading signal:

{market_context}"""

        try:
            # The google-genai SDK 0.8+ supports async calls via .aio
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=self.system_instruction,
                    response_mime_type="application/json",
                    response_schema=TradingSignal,
                    thinking_config=types.ThinkingConfig(
                        include_thoughts=True,
                    ),
                ),
            )

            # Log thoughts if present
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.thought:
                        logger.info(f"Gemini Thoughts: {part.text}")

            if not response.text:
                logger.error("Gemini returned empty response.")
                return None

            data = json.loads(response.text)
            return TradingSignal(**data)

        except Exception as e:
            logger.error(f"Gemini Analysis Error: {e}")
            if isinstance(e, (errors.ServerError, errors.APIError)):
                raise e  # Trigger retry
            return None

    async def assess_news(
        self, news_text: str, market_name: str
    ) -> Optional[NewsQuality]:
        """
        Assesses news relevance and quality.
        """
        prompt = f"""Analyze these news headlines for the '{market_name}' market:

{news_text}"""

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=NewsQuality,
                    thinking_config=types.ThinkingConfig(include_thoughts=True),
                ),
            )

            if not response.text:
                return None

            return NewsQuality(**json.loads(response.text))
        except Exception as e:
            logger.error(f"Gemini News Assessment Error: {e}")
            return None
