from yeuxq.analysis.indicators import (
    atr,
    ema_series,
    last_sma,
    ma_direction,
    pct_change,
    sma_series,
)


def test_sma_series():
    vals = [1, 2, 3, 4, 5]
    s = sma_series(vals, 3)
    assert s[0] is None and s[1] is None
    assert abs(s[2] - 2.0) < 1e-9
    assert abs(s[4] - 4.0) < 1e-9


def test_ema_and_last_sma():
    vals = list(range(1, 21))
    e = ema_series(vals, 5)
    assert e[4] is not None
    assert last_sma(vals, 5) == sum(vals[-5:]) / 5


def test_ma_direction_and_pct():
    up = [float(i) for i in range(20)]
    s = sma_series(up, 5)
    assert ma_direction(s, 3) == "向上"
    assert abs(pct_change(100, 110) - 10) < 1e-9


def test_atr():
    highs = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]
    lows = [9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
    closes = [9.5, 10.5, 11.5, 12.5, 13.5, 14.5, 15.5, 16.5, 17.5, 18.5, 19.5, 20.5]
    v = atr(highs, lows, closes, period=5)
    assert v > 0
