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

        # Distance = |Entry - Stop|
        distance = abs(signal.entry - signal.stop_loss)
        if distance == 0:
            logger.error("Invalid Stop Loss: Distance is 0")
            return False

        # --- 1. Minimum Stop Distance Check (1.0x ATR) ---
        if signal.atr and signal.atr > 0:
            min_stop_dist = 1.0 * signal.atr
            if distance < min_stop_dist:
                old_stop = signal.stop_loss
                if signal.action == Action.BUY:
                    signal.stop_loss = signal.entry - min_stop_dist
                elif signal.action == Action.SELL:
                    signal.stop_loss = signal.entry + min_stop_dist

                logger.warning(
                    f"Risk Adjustment: Stop Loss too tight ({distance:.2f} < 1.0xATR {min_stop_dist:.2f}). "
                    f"Widened from {old_stop} to {signal.stop_loss}."
                )
                distance = min_stop_dist

        # Calculate Target Size based on Risk Rule
        target_size = max_risk_amount / distance
        # Round down to 2 decimal places
        target_size = int(target_size * 100) / 100.0

        logger.info(
            f"Risk Check: Balance={balance:.2f}, MaxRisk={max_risk_amount:.2f}, Distance={distance:.2f}, TargetSize={target_size}"
        )

        if target_size < 0.01:
            logger.error(
                f"Risk Violation: Calculated size {target_size} is below broker minimum (0.01). Stop distance might be too wide."
            )
            return False

        # Override signal size with risk-adjusted size
        if signal.size != target_size:
            logger.info(f"Resizing trade: {signal.size} -> {target_size}")
            signal.size = target_size

        return True
