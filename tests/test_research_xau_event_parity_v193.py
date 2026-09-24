from datetime import UTC, datetime, timedelta

from fx_scanner.models import Bar
from fx_scanner.research_xau_event_parity_v193 import _reaction


def _bar(ts, o, h, l, c):
    return Bar(
        "XAUUSD",
        "M5",
        ts,
        float(o),
        float(h),
        float(l),
        float(c),
        1,
        0.0,
        0.0,
    )


def test_ctrader_parity_reaction_is_atr_normalized():
    event = datetime(2026, 9, 24, 12, 30, tzinfo=UTC)
    bars = []
    start = event - timedelta(minutes=90)
    price = 2000.0
    for i in range(31):
        ts = start + timedelta(minutes=5 * i)
        open_ = price
        close = price + 0.5
        bars.append(_bar(ts, open_, close + 0.2, open_ - 0.2, close))
        price = close
    out = _reaction(tuple(bars), event)
    assert out["r5m_atr"] is not None
    assert out["r15m_atr"] is not None
    assert out["r15m_atr"] > 0
