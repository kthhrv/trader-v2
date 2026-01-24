import pytest
from unittest.mock import patch
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from app.services.market_status import MarketStatusService


@pytest.fixture
def service():
    return MarketStatusService()


def test_is_holiday_season(service):
    # Dec 25th -> True
    assert service._is_holiday_season(date(2023, 12, 25)) is True
    # Jan 1st -> True
    assert service._is_holiday_season(date(2024, 1, 1)) is True
    # Jan 5th -> False
    assert service._is_holiday_season(date(2024, 1, 5)) is False
    # Nov 20th -> False
    assert service._is_holiday_season(date(2023, 11, 20)) is False


@patch("app.services.market_status.datetime")
def test_is_holiday_uk(mock_datetime, service):
    # Mock London Time: Dec 25 (Christmas)
    mock_now = datetime(2023, 12, 25, 10, 0, tzinfo=ZoneInfo("Europe/London"))
    mock_datetime.now.return_value = mock_now

    # We need to bypass the _is_holiday_season check to test the actual holiday library
    # So we pick a non-season holiday: Good Friday (e.g. 2024-03-29) or May Day

    # Let's use 2023-12-25 but patch _is_holiday_season to False so we test the library
    with patch.object(service, "_is_holiday_season", return_value=False):
        assert service.is_holiday("IX.D.FTSE.DAILY.IP") is True


@patch("app.services.market_status.datetime")
def test_is_holiday_us(mock_datetime, service):
    # July 4th
    mock_now = datetime(2023, 7, 4, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    mock_datetime.now.return_value = mock_now

    assert service.is_holiday("IX.D.SPTRD.DAILY.IP") is True


@patch("app.services.market_status.datetime")
def test_market_open_day(mock_datetime, service):
    # A random Tuesday in Feb
    mock_now = datetime(2024, 2, 6, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    mock_datetime.now.return_value = mock_now

    assert service.is_holiday("IX.D.SPTRD.DAILY.IP") is False


@patch("app.services.market_status.datetime")
def test_get_market_close_datetime_us(mock_datetime, service):
    # Set Now to 10:00 AM NY
    ny_tz = ZoneInfo("America/New_York")
    mock_now = datetime(2023, 6, 1, 10, 0, 0, tzinfo=ny_tz)
    mock_datetime.now.return_value = mock_now

    close_dt = service.get_market_close_datetime("IX.D.SPTRD.DAILY.IP")

    # Expected: Today at 16:00
    expected = mock_now.replace(hour=16, minute=0, second=0, microsecond=0)
    assert close_dt == expected
    assert close_dt.tzinfo == ny_tz


@patch("app.services.market_status.datetime")
def test_get_market_close_datetime_past_close(mock_datetime, service):
    # Set Now to 17:00 PM NY (Past Close)
    ny_tz = ZoneInfo("America/New_York")
    mock_now = datetime(2023, 6, 1, 17, 0, 0, tzinfo=ny_tz)
    mock_datetime.now.return_value = mock_now

    close_dt = service.get_market_close_datetime("IX.D.SPTRD.DAILY.IP")

    # Expected: Tomorrow at 16:00
    expected = mock_now.replace(hour=16, minute=0, second=0, microsecond=0) + timedelta(
        days=1
    )
    assert close_dt == expected
