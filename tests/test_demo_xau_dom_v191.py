from datetime import UTC, datetime, timedelta

from fx_scanner.demo_xau_dom_v191 import DomFrame, analyze_dom_frames


def _frame(
    i: int,
    *,
    bid_sizes=(100.0, 80.0, 60.0),
    ask_sizes=(100.0, 80.0, 60.0),
):
    base = datetime(2026, 9, 24, 0, 0, tzinfo=UTC) + timedelta(seconds=i)
    bids = tuple((4288.9 - 0.1 * j, float(size)) for j, size in enumerate(bid_sizes))
    asks = tuple((4289.0 + 0.1 * j, float(size)) for j, size in enumerate(ask_sizes))
    return DomFrame(base, bids, asks, i + 1, len(bids) + len(asks))


def test_dom_balanced_book_stays_contested():
    frames = tuple(_frame(i) for i in range(8))
    result = analyze_dom_frames(frames)
    assert result["state"] == "BALANCED_OR_CONTESTED"
    assert abs(result["last_imbalance"]) < 1e-9
    assert result["execution_authority"] is False
    assert result["execution_influence"] is False


def test_dom_bid_stacking_resolves_bid_dominant():
    frames = []
    for i in range(8):
        bid = (100 + i * 40, 90 + i * 20, 70 + i * 10)
        ask = (90, 70, 50)
        frames.append(_frame(i, bid_sizes=bid, ask_sizes=ask))
    result = analyze_dom_frames(tuple(frames))
    assert result["state"] == "BID_DOMINANT"
    assert result["last_imbalance"] > 0.10
    assert result["bid_top5_change"] > 0
    assert result["dom_pressure_score"] >= 62


def test_dom_ask_stacking_resolves_ask_dominant():
    frames = []
    for i in range(8):
        bid = (90, 70, 50)
        ask = (100 + i * 40, 90 + i * 20, 70 + i * 10)
        frames.append(_frame(i, bid_sizes=bid, ask_sizes=ask))
    result = analyze_dom_frames(tuple(frames))
    assert result["state"] == "ASK_DOMINANT"
    assert result["last_imbalance"] < -0.10
    assert result["ask_top5_change"] > 0
    assert result["dom_pressure_score"] <= 38


def test_dom_insufficient_samples_never_authorizes():
    result = analyze_dom_frames(tuple(_frame(i) for i in range(3)))
    assert result["state"] == "INSUFFICIENT_DOM_SAMPLES"
    assert result["execution_authority"] is False
