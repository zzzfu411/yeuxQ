from yeuxq.providers.orderflow import OrderFlowProvider


def test_map_bs():
    assert OrderFlowProvider._map_bs(2) == "买盘"
    assert OrderFlowProvider._map_bs(1) == "卖盘"
    assert OrderFlowProvider._map_bs(4) == "中性"


def test_lot_multiplier():
    from yeuxq.providers.orderflow import _lot_multiplier

    assert _lot_multiplier("600519") == 100
    assert _lot_multiplier("510300") == 1


def test_adaptive_thresholds_high_price():
    from yeuxq.providers.orderflow import adaptive_thresholds

    large, super_amt = adaptive_thresholds(1343.0)
    assert large > 1_000_000  # 茅台不应再用 20 万
    assert super_amt > large
    cheap_l, cheap_s = adaptive_thresholds(5.0)
    assert cheap_l == 200_000
    assert cheap_s == 1_000_000
