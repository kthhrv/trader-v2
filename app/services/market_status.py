from datetime import date, datetime, timedelta
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
        self.au_holidays = holidays.Australia(subdiv="NSW")  # type: ignore
        self.de_holidays = holidays.Germany(subdiv="HE")  # type: ignore

    def _get_country_code(self, epic: str) -> str:
        """
        Maps an IG epic to a country code for holiday lookup.
        """
        if "FTSE" in epic:
            return "GB"
        elif (
            "SPX" in epic
            or "US500" in epic
            or "NASDAQ" in epic
            or "WALL" in epic
            or "SPTRD" in epic
        ):
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

    def is_market_open(self, epic: str) -> bool:
        """
        Checks if the market is currently open for trading (not holiday, not weekend, within hours).
        """
        if self.is_holiday(epic):
            return False

        schedule = self._get_market_hours(epic)
        tz = ZoneInfo(schedule["timezone"])
        now = datetime.now(tz)

        # Weekend check
        if now.weekday() >= 5:  # 5=Saturday, 6=Sunday
            return False

        current_time = now.time()
        open_time = datetime.strptime(schedule["open"], "%H:%M").time()
        close_time = datetime.strptime(schedule["close"], "%H:%M").time()

        return open_time <= current_time <= close_time

    def _is_holiday_season(self, d: date) -> bool:
        """
        Checks if the date falls within the low-liquidity holiday season (Dec 20 - Jan 4).
        """
        if d.month == 12 and d.day >= 20:
            return True
        if d.month == 1 and d.day <= 4:
            return True
        return False

    def _get_market_hours(self, epic: str) -> dict:
        """
        Returns the market hours (open/close) for a given epic.
        Times are in the market's local timezone.
        """
        country = self._get_country_code(epic)

        # Default fallback
        schedule = {"open": "09:00", "close": "17:00", "timezone": "UTC"}

        if country == "GB":  # FTSE
            schedule = {"open": "08:00", "close": "16:30", "timezone": "Europe/London"}
        elif country == "US":  # SPX, NASDAQ, DOW
            schedule = {
                "open": "09:30",
                "close": "16:00",
                "timezone": "America/New_York",
            }
        elif country == "JP":  # Nikkei
            schedule = {"open": "09:00", "close": "15:00", "timezone": "Asia/Tokyo"}
        elif country == "DE":  # DAX
            schedule = {"open": "09:00", "close": "17:30", "timezone": "Europe/Berlin"}
        elif country == "AU":  # ASX
            schedule = {
                "open": "10:00",
                "close": "16:00",
                "timezone": "Australia/Sydney",
            }

        return schedule

    def get_market_close_datetime(self, epic: str) -> datetime:
        """
        Returns the next market close time as a localized datetime object.
        """
        schedule = self._get_market_hours(epic)
        close_time_str = schedule["close"]
        timezone_str = schedule["timezone"]

        tz = ZoneInfo(timezone_str)
        now_tz = datetime.now(tz)

        hour, minute = map(int, close_time_str.split(":"))

        close_dt = now_tz.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # If it's already past today's close, the next close is tomorrow (simplification)
        if now_tz > close_dt:
            close_dt += timedelta(days=1)

        return close_dt
