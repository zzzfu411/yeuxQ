from yeuxq.analysis.engine import run_analysis
from yeuxq.analysis.pattern import pattern_score
from yeuxq.analysis.plugins.rule_predictor import RulePredictor
from yeuxq.domain.models import FundFlow, Kline, PatternResult
from yeuxq.settings import get_settings


def _synth_up_klines(n: int = 120) -> list[Kline]:
    ks: list[Kline] = []
    price = 100.0
    for i in range(n):
        o = price
        c = price * (1 + 0.004)
        h = c * 1.01
        lo = o * 0.99
        ks.append(
            Kline(
                date=f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                open=round(o, 2),
                close=round(c, 2),
                high=round(h, 2),
                low=round(lo, 2),
                volume=10000 + i * 10,
                amount=1e7,
                turnover=1.5,
            )
        )
        price = c
    # fix invalid dates roughly ok for algorithm
    for i, k in enumerate(ks):
        k.date = "2024-01-01"
        k.date = f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}"
    return ks


def test_run_analysis_uptrend():
    ks = _synth_up_klines(150)
    flows = [
        FundFlow(
            date=f"d{i}",
            main_net=1e8,
            super_large_net=5e7,
            large_net=5e7,
            medium_net=-1e7,
            small_net=-2e7,
            main_pct=5,
        )
        for i in range(10)
    ]
    result = run_analysis(ks, flows=flows, settings=get_settings())
    assert result.score >= 50
    assert result.trend is not None
    assert result.momentum is not None
    assert result.prediction is not None
    assert 0 <= result.prediction.prob_up <= 1
    from yeuxq.analysis.rust_bridge import rust_status

    assert rust_status().get("available") in (True, False)
    assert result.trade_plan.entry_price > 0
    assert result.trade_plan.stop_loss < result.trade_plan.entry_price
    assert "趋势" in result.module_scores


def test_pattern_score():
    ps = [
        PatternResult(name="双底", direction="看涨", confidence=60, status="已突破"),
        PatternResult(name="双顶", direction="看跌", confidence=50, status="形成中"),
    ]
    s = pattern_score(ps)
    assert 20 <= s <= 100


def test_rule_predictor():
    p = RulePredictor().predict(
        {
            "score": 75,
            "trend": 80,
            "momentum": 70,
            "volume_price": 70,
            "breakout": 60,
            "m_score": 70,
            "main_flow_streak": 3,
            "horizon_days": 5,
        }
    )
    assert p.direction in ("看多", "中性", "看空")
    assert p.prob_up > 0.5
