import pytest
import pandas as pd
import numpy as np
from app.services.technical_analysis import TechnicalAnalysisService


@pytest.fixture
def mock_df():
    """Creates a dummy DataFrame with OHLCV data."""
    dates = pd.date_range(start="2023-01-01", periods=50, freq="15min")
    data = {
        "open": np.linspace(100, 150, 50),
        "high": np.linspace(102, 152, 50),
        "low": np.linspace(98, 148, 50),
        "close": np.linspace(101, 151, 50),
        "volume": np.random.randint(100, 1000, 50),
    }
    return pd.DataFrame(data, index=dates)


def test_calculate_indicators(mock_df):
    df = TechnicalAnalysisService.calculate_indicators(mock_df)
    assert "ATR" in df.columns
    assert "RSI" in df.columns
    assert "EMA_20" in df.columns
    assert "ADX" in df.columns
    assert not df["EMA_20"].isna().all()


def test_calculate_rvol(mock_df):
    # Set the last volume to be 2x the average
    avg_vol = mock_df["volume"].mean()
    mock_df.iloc[-1, mock_df.columns.get_loc("volume")] = int(avg_vol * 2.0)

    rvol = TechnicalAnalysisService.calculate_rvol(mock_df, window=50)
    # Since we modified the last one, the rolling avg will shift slightly, but rvol should be close to 2.0
    assert rvol > 1.8


def test_calculate_rvol_low_volume(mock_df):
    avg_vol = mock_df["volume"].mean()
    mock_df.iloc[-1, mock_df.columns.get_loc("volume")] = int(avg_vol * 0.5)

    rvol = TechnicalAnalysisService.calculate_rvol(mock_df, window=50)
    assert rvol < 0.6


def test_calculate_slope(mock_df):
    # Setup a steep uptrend
    mock_df["EMA_20"] = pd.Series(np.linspace(100, 200, 50), index=mock_df.index)
    mock_df["ATR"] = 1.0  # Constant ATR for easy calculation

    # Slope = (EMA[now] - EMA[prev]) / ATR
    # Step = (200-100)/49 ~= 2.04
    # Slope ~= 2.04 / 1.0 = 2.04

    slope = TechnicalAnalysisService.calculate_slope(mock_df)
    assert slope > 1.5


def test_calculate_slope_flat(mock_df):
    # Setup a flat trend
    mock_df["EMA_20"] = 100.0
    mock_df["ATR"] = 5.0

    slope = TechnicalAnalysisService.calculate_slope(mock_df)
    assert slope == 0.0
