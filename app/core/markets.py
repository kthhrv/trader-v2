from typing import Dict, Any

MARKET_CONFIGS: Dict[str, Dict[str, Any]] = {
    "london": {
        "epic": "IX.D.FTSE.DAILY.IP",
        "name": "FTSE 100",
        "timezone": "Europe/London",
        "schedule": {"day_of_week": "mon-fri", "hour": 7, "minute": 55},
        "max_spread": 2.0,
    },
    "ny": {
        "epic": "IX.D.SPTRD.DAILY.IP",
        "name": "S&P 500",
        "timezone": "America/New_York",
        "schedule": {"day_of_week": "mon-fri", "hour": 9, "minute": 25},
        "max_spread": 1.6,
    },
    "nikkei": {
        "epic": "IX.D.NIKKEI.DAILY.IP",
        "name": "Nikkei 225",
        "timezone": "Asia/Tokyo",
        "schedule": {"day_of_week": "mon-fri", "hour": 8, "minute": 55},
        "max_spread": 8.0,
    },
    "germany": {
        "epic": "IX.D.DAX.DAILY.IP",
        "name": "DAX 40",
        "timezone": "Europe/London",
        "schedule": {"day_of_week": "mon-fri", "hour": 7, "minute": 55},
        "max_spread": 2.5,
    },
    "australia": {
        "epic": "IX.D.ASX.MONTH1.IP",
        "name": "ASX 200",
        "timezone": "Australia/Sydney",
        "schedule": {"day_of_week": "mon-fri", "hour": 9, "minute": 55},
        "max_spread": 3.0,
    },
    "us_tech": {
        "epic": "IX.D.NASDAQ.CASH.IP",
        "name": "Nasdaq 100",
        "timezone": "America/New_York",
        "schedule": {"day_of_week": "mon-fri", "hour": 9, "minute": 25},
        "max_spread": 2.0,
    },
}
