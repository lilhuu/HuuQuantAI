from core.backtest_validation import build_higher_timeframe_trend


def _candles(closes, timeframe="4h"):
    return [
        {
            "symbol": "BTC/USDT",
            "period": timeframe,
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 100,
        }
        for close in closes
    ]


def test_trend_up_when_both_windows_positive():
    closes = [100 + index * 1.5 for index in range(80)]
    result = build_higher_timeframe_trend(_candles(closes), timeframe="4h")

    assert result.direction == "up"
    assert result.four_hour_change_pct >= 1.5
    assert result.daily_change_pct >= 2.0


def test_trend_down_when_both_windows_negative():
    closes = [220 - index * 1.5 for index in range(80)]
    result = build_higher_timeframe_trend(_candles(closes), timeframe="4h")

    assert result.direction == "down"
    assert result.four_hour_change_pct <= -1.5
    assert result.daily_change_pct <= -2.0


def test_neutral_when_windows_are_mixed():
    closes = [100] * 67 + [100 + index * 0.133 for index in range(13)]
    result = build_higher_timeframe_trend(_candles(closes), timeframe="4h")

    assert result.direction == "neutral"


def test_insufficient_data_returns_neutral():
    result = build_higher_timeframe_trend(_candles([100, 101]), timeframe="1h")

    assert result.direction == "neutral"
    assert result.four_hour_change_pct == 0.0
    assert result.daily_change_pct == 0.0
