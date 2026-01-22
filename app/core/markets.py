from typing import Dict, Any

MARKET_CONFIGS: Dict[str, Dict[str, Any]] = {
    "london": {
        "epic": "IX.D.FTSE.DAILY.IP",
        "name": "FTSE 100",
        "timezone": "Europe/London",
    },
    "ny": {
        "epic": "IX.D.SPTRD.DAILY.IP",
        "name": "S&P 500",
        "timezone": "America/New_York",
    },
    "nikkei": {
        "epic": "IX.D.NIKKEI.DAILY.IP",
        "name": "Nikkei 225",
        "timezone": "Asia/Tokyo",
    },
    "germany": {
        "epic": "IX.D.DAX.DAILY.IP",
        "name": "DAX 40",
        "timezone": "Europe/London",
    },
    "australia": {
        "epic": "IX.D.ASX.MONTH1.IP",
        "name": "ASX 200",
        "timezone": "Australia/Sydney",
    },
    "us_tech": {
        "epic": "IX.D.NASDAQ.CASH.IP",
        "name": "Nasdaq 100",
        "timezone": "America/New_York",
    },
}
