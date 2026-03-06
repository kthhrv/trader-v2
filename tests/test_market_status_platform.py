import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from app.services.market_status import MarketStatusService


@pytest.fixture
def service():
    return MarketStatusService()


def test_returns_none_when_market_open(service):
    """During ASX trading hours on a weekday, streaming should be active."""
    # Wednesday 11:00 Sydney = market open (ASX opens 10:00)
    now = datetime(2026, 3, 4, 11, 0, 0, tzinfo=ZoneInfo("Australia/Sydney"))
    result = service.get_next_streaming_start(now=now)
    assert result is None


def test_returns_next_open_on_weekend(service):
    """Saturday should return Mon ASX open minus 10 min (earliest market)."""
    # Saturday 12:00 UTC
    now = datetime(2026, 3, 7, 12, 0, 0, tzinfo=ZoneInfo("UTC"))
    result = service.get_next_streaming_start(now=now)

    assert result is not None
    # ASX opens Mon 10:00 Sydney. In early March, Sydney is AEDT (UTC+11).
    # So 10:00 AEDT = 23:00 UTC Sunday. Minus 10 min = 22:50 UTC Sunday.
    assert result.weekday() == 6  # Sunday in UTC
    assert result.hour == 22
    assert result.minute == 50


def test_returns_next_open_on_friday_night(service):
    """Friday 23:00 UTC — all markets closed, should return Sun ~22:50 UTC (ASX Mon open)."""
    now = datetime(2026, 3, 6, 23, 0, 0, tzinfo=ZoneInfo("UTC"))
    result = service.get_next_streaming_start(now=now)

    assert result is not None
    # Next trading day is Monday March 9. ASX opens 10:00 AEDT = 23:00 UTC Sun.
    # Minus 10 min = 22:50 UTC Sunday.
    assert result.weekday() == 6  # Sunday
    assert result.hour == 22
    assert result.minute == 50


def test_returns_next_open_after_all_closed(service):
    """Weekday evening after all markets closed — next day's earliest open."""
    # Wednesday 22:00 UTC — all markets closed
    now = datetime(2026, 3, 4, 22, 0, 0, tzinfo=ZoneInfo("UTC"))
    result = service.get_next_streaming_start(now=now)

    assert result is not None
    # ASX opens Thu 10:00 AEDT = Wed 23:00 UTC. Minus 10 = 22:50 UTC Wed.
    # But now is 22:00 UTC Wed, so 22:50 is still in the future.
    assert result.minute == 50


def test_dst_transition_sydney_aedt_to_aest(service):
    """ASX open time shifts UTC offset when Sydney switches from AEDT to AEST.

    In 2026, Sydney DST ends first Sunday of April (April 5).
    AEDT (UTC+11) -> AEST (UTC+10). ASX opens 10:00 local either way,
    but the UTC equivalent shifts by 1 hour.
    """
    # Friday April 3, 23:00 UTC — all markets closed, next open is Mon April 6
    # April 6 is after DST ends, so Sydney is AEST (UTC+10)
    now = datetime(2026, 4, 3, 23, 0, 0, tzinfo=ZoneInfo("UTC"))
    result = service.get_next_streaming_start(now=now)

    assert result is not None
    # ASX opens Mon 10:00 AEST (UTC+10) = Mon 00:00 UTC. Minus 10 min = Sun 23:50 UTC.
    # Before DST change this would have been Sun 22:50 UTC (AEDT, UTC+11).
    assert result.weekday() == 6  # Sunday
    assert result.hour == 23
    assert result.minute == 50


def test_dst_transition_sydney_before_change(service):
    """Before DST change, AEDT (UTC+11) applies — UTC time is 1 hour earlier."""
    # Friday March 27, 23:00 UTC — still AEDT
    now = datetime(2026, 3, 27, 23, 0, 0, tzinfo=ZoneInfo("UTC"))
    result = service.get_next_streaming_start(now=now)

    assert result is not None
    # ASX opens Mon 10:00 AEDT (UTC+11) = Sun 23:00 UTC. Minus 10 = Sun 22:50 UTC.
    assert result.weekday() == 6  # Sunday
    assert result.hour == 22
    assert result.minute == 50
