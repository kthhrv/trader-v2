import pytest
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo
from app.services.market_status import MarketStatusService

# Alias real datetime to use in side_effects
from datetime import datetime as RealDatetime


@pytest.fixture
def service():
    return MarketStatusService()


@patch("app.services.market_status.datetime")
def test_is_market_open_us_regular(mock_datetime, service):
    # Setup strptime to use real implementation
    mock_datetime.strptime.side_effect = lambda s, f: RealDatetime.strptime(s, f)

    # US Market: 9:30 - 16:00
    # Case 1: Open (10:00 AM)
    mock_now = datetime(
        2023, 6, 1, 10, 0, 0, tzinfo=ZoneInfo("America/New_York")
    )  # Thursday
    mock_datetime.now.return_value = mock_now

    assert service.is_market_open("IX.D.SPTRD.DAILY.IP") is True


@patch("app.services.market_status.datetime")
def test_is_market_open_us_premarket(mock_datetime, service):
    mock_datetime.strptime.side_effect = lambda s, f: RealDatetime.strptime(s, f)

    # Case 2: Pre-market (9:00 AM)
    mock_now = datetime(2023, 6, 1, 9, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    mock_datetime.now.return_value = mock_now
    assert service.is_market_open("IX.D.SPTRD.DAILY.IP") is False


@patch("app.services.market_status.datetime")
def test_is_market_open_us_postmarket(mock_datetime, service):
    mock_datetime.strptime.side_effect = lambda s, f: RealDatetime.strptime(s, f)

    # Case 3: After close (16:01 PM)
    mock_now = datetime(2023, 6, 1, 16, 1, 0, tzinfo=ZoneInfo("America/New_York"))
    mock_datetime.now.return_value = mock_now
    assert service.is_market_open("IX.D.SPTRD.DAILY.IP") is False


@patch("app.services.market_status.datetime")
def test_is_market_open_weekend(mock_datetime, service):
    mock_datetime.strptime.side_effect = lambda s, f: RealDatetime.strptime(s, f)

    # Case 4: Weekend (Saturday)
    mock_now = datetime(2023, 6, 3, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    mock_datetime.now.return_value = mock_now
    assert service.is_market_open("IX.D.SPTRD.DAILY.IP") is False


@patch("app.services.market_status.datetime")
def test_is_market_open_holiday(mock_datetime, service):
    mock_datetime.strptime.side_effect = lambda s, f: RealDatetime.strptime(s, f)

    # Case 5: Holiday (July 4th)
    mock_now = datetime(2023, 7, 4, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    mock_datetime.now.return_value = mock_now
    assert service.is_market_open("IX.D.SPTRD.DAILY.IP") is False
