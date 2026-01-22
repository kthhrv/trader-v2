from datetime import date, datetime
from zoneinfo import ZoneInfo
import holidays
from app.core.logger import logger
from app.core.markets import MARKET_CONFIGS


class MarketStatusService:
    """
    Checks if the current day is a public holiday for a specific market.
    """

    def __init__(self):
        # Initialize holiday calendars for key markets
        self.uk_holidays = holidays.UnitedKingdom()  # type: ignore
        try:
            self.us_holidays = holidays.NYSE()  # type: ignore
        except NotImplementedError:
            self.us_holidays = holidays.UnitedStates()  # type: ignore

        self.jp_holidays = holidays.Japan()  # type: ignore
        self.au_holidays = holidays.Australia(state="NSW")  # type: ignore
        self.de_holidays = holidays.Germany(state="HE")  # type: ignore

    def _get_country_code(self, epic: str) -> str:
        """
        Maps an IG epic to a country code for holiday lookup.
        """
        if "FTSE" in epic:
            return "GB"
        elif "SPX" in epic or "US500" in epic or "NASDAQ" in epic or "WALL" in epic:
            return "US"
        elif "NIKKEI" in epic:
            return "JP"
        elif "DAX" in epic or "DE30" in epic:
            return "DE"
        elif "ASX" in epic:
            return "AU"
        elif "GBP" in epic:
            return "GB"  # Forex usually trades, but liquidity low on bank holidays
        elif "EUR" in epic:
            return "DE"  # Proxy for Eurozone
        return "GLOBAL"

    def is_holiday(self, epic: str) -> bool:
        """
        Determines if the market associated with the epic is closed due to a holiday.
        Checks the holiday status for the date in the MARKET'S timezone, not local time.
        """
        country_code = self._get_country_code(epic)

        # Determine market timezone
        tz_name = "UTC"
        # Find config for this epic (reverse lookup)
        for _, cfg in MARKET_CONFIGS.items():
            if cfg["epic"] == epic:
                tz_name = cfg["timezone"]
                break

        market_tz = ZoneInfo(tz_name)
        target_date = datetime.now(market_tz).date()

        holiday_name = None

        # 1. Check Custom Holiday Season Block (Dec 20 - Jan 4)
        if self._is_holiday_season(target_date):
            logger.warning(
                f"Market {country_code} is closed for Holiday Season (Dec 20 - Jan 4). Trading skipped."
            )
            return True

        # 2. Check Official Public Holidays
        is_closed = False

        if country_code == "GB":
            if target_date in self.uk_holidays:
                is_closed = True
                holiday_name = self.uk_holidays.get(target_date)

        elif country_code == "US":
            if target_date in self.us_holidays:
                is_closed = True
                holiday_name = self.us_holidays.get(target_date)

        elif country_code == "JP":
            if target_date in self.jp_holidays:
                is_closed = True
                holiday_name = self.jp_holidays.get(target_date)

        elif country_code == "DE":
            if target_date in self.de_holidays:
                is_closed = True
                holiday_name = self.de_holidays.get(target_date)

        elif country_code == "AU":
            if target_date in self.au_holidays:
                is_closed = True
                holiday_name = self.au_holidays.get(target_date)

        if is_closed:
            logger.warning(
                f"Market {country_code} is CLOSED on {target_date} for {holiday_name if holiday_name else 'Public Holiday'}. Trading skipped."
            )
            return True

        return False

    def _is_holiday_season(self, d: date) -> bool:
        """
        Checks if the date falls within the low-liquidity holiday season (Dec 20 - Jan 4).
        """
        if d.month == 12 and d.day >= 20:
            return True
        if d.month == 1 and d.day <= 4:
            return True
        return False
