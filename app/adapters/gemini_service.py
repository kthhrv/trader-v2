import json
from enum import Enum
from typing import Optional, Type, TypeVar

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
from app.core.prompts import (
    STRATEGY_ANALYST_INSTRUCTION,
    NEWS_ANALYST_INSTRUCTION,
    POST_MORTEM_INSTRUCTION,
)

T = TypeVar("T", bound=BaseModel)


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    WAIT = "WAIT"
    ERROR = "ERROR"


class EntryType(str, Enum):
    BREAKOUT = "BREAKOUT"
    PULLBACK = "PULLBACK"
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
    entry_type: EntryType = EntryType.BREAKOUT
    stop_loss: float
    take_profit: Optional[float] = None
    size: float
    atr: float
    use_trailing_stop: bool
    confidence: str
    reasoning: str


class PostMortemReport(BaseModel):
    did_follow_plan: bool
    stop_loss_critique: str
    slippage_impact: str
    reasoning_quality: str
    key_lesson: str
    verdict: str


class GeminiService:
    """
    Async service for Gemini AI analysis.
    Uses structured outputs and thinking (Reasoning) models.
    """

    def __init__(self, model_name: str = "gemini-3-flash-preview"):
        self.model_name = model_name
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY.get_secret_value())

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((errors.ServerError, errors.APIError)),
    )
    async def _generate_structured(
        self, prompt: str, system_instruction: str, response_model: Type[T]
    ) -> Optional[T]:
        """
        Generic helper for structured generation.
        """
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=response_model,
                    thinking_config=types.ThinkingConfig(
                        include_thoughts=True,
                        thinking_level=types.ThinkingLevel.HIGH,
                    ),
                ),
            )

            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.thought:
                        logger.info(f"Gemini Thoughts: {part.text}")

            if not response.text:
                logger.error("Gemini returned empty response.")
                return None

            data = json.loads(response.text)
            return response_model(**data)

        except Exception as e:
            logger.error(f"Gemini API Error: {e}")
            if isinstance(e, (errors.ServerError, errors.APIError)):
                raise e
            return None

    async def analyze_market(
        self, market_context: str, strategy_name: str = "Market Open"
    ) -> Optional[TradingSignal]:
        """
        Analyzes market data and returns a structured TradingSignal.
        """
        prompt = f"""Analyze the following {strategy_name} market data and generate a trading signal:

{market_context}"""

        return await self._generate_structured(
            prompt, STRATEGY_ANALYST_INSTRUCTION, TradingSignal
        )

    async def assess_news(
        self, news_text: str, market_name: str
    ) -> Optional[NewsQuality]:
        """
        Assesses news relevance and quality.
        """
        prompt = f"""Analyze these news headlines for the '{market_name}' market:

{news_text}"""

        return await self._generate_structured(
            prompt, NEWS_ANALYST_INSTRUCTION, NewsQuality
        )

    async def generate_post_mortem(
        self, trade_log: dict, execution_data: dict
    ) -> Optional[PostMortemReport]:
        """
        Generates a post-mortem analysis for a completed trade.
        """
        prompt = f"""Conduct a post-mortem analysis for the following trade:

Trade Log:
{json.dumps(trade_log, indent=2)}

Execution Data:
{json.dumps(execution_data, indent=2)}
"""
        return await self._generate_structured(
            prompt, POST_MORTEM_INSTRUCTION, PostMortemReport
        )
