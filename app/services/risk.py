from app.core.config import settings
from app.core.logger import logger
from app.adapters.ig_client import AsyncIGClient
from app.adapters.gemini_service import TradingSignal, Action


class RiskManager:
    def __init__(self, ig_client: AsyncIGClient):
        self.ig_client = ig_client

    async def validate_signal(self, signal: TradingSignal) -> bool:
        """
        Validates the signal against risk management rules.
        """
        if signal.action == Action.WAIT:
            return True

        # Fetch Account Balance
        try:
            # Note: ig_client.get_account_balance returns TOTAL balance (equity)
            # This allows concurrent trades as margin doesn't reduce the risk base.
            balance = await self.ig_client.get_account_balance(
                settings.TRADING_ACCOUNT_ENV
            )
        except Exception as e:
            logger.error(f"Failed to fetch balance for validation: {e}")
            return False  # Fail safe

        # Calculate Risk Rules
        # Risk per Trade = Balance * RISK_PER_TRADE_PERCENT
        max_risk_amount = balance * settings.RISK_PER_TRADE_PERCENT

        # Floor Check: Ensure balance after potential loss remains above MIN_ACCOUNT_BALANCE
        if settings.MIN_ACCOUNT_BALANCE > 0:
            allowed_loss = balance - settings.MIN_ACCOUNT_BALANCE
            if allowed_loss <= 0:
                logger.error(
                    f"Total Balance ({balance}) is below Minimum Floor ({settings.MIN_ACCOUNT_BALANCE}). Trading halted."
                )
                return False
            # Cap max risk by the distance to the floor
            if max_risk_amount > allowed_loss:
                logger.warning(
                    f"Capping Risk to protect Floor: {max_risk_amount:.2f} -> {allowed_loss:.2f}"
                )
                max_risk_amount = allowed_loss

        # Trade Risk = Size * Distance
        # Distance = |Entry - Stop|
        distance = abs(signal.entry - signal.stop_loss)
        if distance == 0:
            logger.error("Invalid Stop Loss: Distance is 0")
            return False

        trade_risk = signal.size * distance

        logger.info(
            f"Validation: Balance={balance:.2f}, MaxRisk={max_risk_amount:.2f}, TradeRisk={trade_risk:.2f}"
        )

        if trade_risk > max_risk_amount:
            logger.error(
                f"Risk Violation: Trade Risk ({trade_risk:.2f}) > Max Risk ({max_risk_amount:.2f}). Rejecting trade."
            )
            return False

        return True
