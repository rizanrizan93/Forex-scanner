from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fx_scanner.research_xau_event_reaction_v193 import (
    HistoricalEvent,
    build_reaction_atlas,
    classify_event_family,
    cluster_events,
    parse_release_number,
    reaction_for_cluster,
)


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


def _bars(start: datetime, count: int = 320):
    rows = []
    price = 2000.0
    for i in range(count):
        ts = start + timedelta(minutes=5 * i)
        drift = 0.10 if i < 220 else 0.02
        open_ = price
        close = price + drift
        high = max(open_, close) + 0.25
        low = min(open_, close) - 0.20
        rows.append(Bar(ts, open_, high, low, close))
        price = close
    return rows


def test_classify_relevant_usd_event_families():
    assert classify_event_family("Non-Farm Employment Change") == "NFP_EMPLOYMENT"
    assert classify_event_family("Unemployment Claims") == "JOBLESS_CLAIMS"
    assert classify_event_family("Core CPI m/m") == "CPI"
    assert classify_event_family("FOMC Member Williams Speaks") == "FED_SPEECH"


def test_parse_release_number_handles_common_calendar_units():
    assert parse_release_number("201K") == 201000.0
    assert parse_release_number("3.2%") == 0.032
    assert parse_release_number("-12.5B") == -12_500_000_000.0
    assert parse_release_number("") is None


def test_same_timestamp_events_are_clustered_and_not_single_attributed():
    at = datetime(2026, 9, 24, 12, 30, tzinfo=UTC)
    events = [
        HistoricalEvent(
            "a",
            at,
            "Unemployment Claims",
            "JOBLESS_CLAIMS",
            "MEDIUM",
            "TEST",
            "SECONDARY",
            201000,
            200000,
            196000,
        ),
        HistoricalEvent(
            "b",
            at,
            "Current Account",
            "CURRENT_ACCOUNT",
            "MEDIUM",
            "TEST",
            "OFFICIAL",
            -255e9,
            -250e9,
            -226.8e9,
        ),
    ]
    clusters = cluster_events(events)
    assert len(clusters) == 1
    assert clusters[0].attribution == "MULTI_EVENT_CLUSTER"
    assert set(clusters[0].families) == {"CURRENT_ACCOUNT", "JOBLESS_CLAIMS"}


def test_reaction_is_atr_normalized_and_keeps_technical_context():
    start = datetime(2026, 9, 23, 0, 0, tzinfo=UTC)
    bars = _bars(start, 360)
    at = start + timedelta(minutes=5 * 250)
    event = HistoricalEvent(
        "cpi-1",
        at,
        "Core CPI m/m",
        "CPI",
        "HIGH",
        "TEST",
        "SECONDARY_ARCHIVE",
        0.004,
        0.003,
        0.002,
    )
    cluster = cluster_events((event,))[0]
    row = reaction_for_cluster(cluster, bars)
    assert row is not None
    assert row["family"] == "CPI"
    assert row["attribution"] == "SINGLE_EVENT"
    assert row["surprise"]["sign"] == "POSITIVE"
    assert row["pre_context"]["state"] == "AVAILABLE"
    assert row["pre_context"]["atr14"] > 0
    assert row["r15m_atr"] is not None
    assert row["execution_authority"] if "execution_authority" in row else True


def test_atlas_reports_historical_frequency_not_probability():
    rows = []
    base = datetime(2012, 1, 1, tzinfo=UTC)
    for i in range(40):
        rows.append(
            {
                "scheduled_at": (base + timedelta(days=i)).isoformat(),
                "family": "CPI",
                "impact": "HIGH",
                "r5m_atr": 0.4 if i % 2 == 0 else -0.2,
                "r15m_atr": 0.6 if i < 24 else -0.5,
                "whipsaw15m": i % 5 == 0,
                "surprise": {"sign": "POSITIVE" if i < 20 else "NEGATIVE"},
                "pre_context": {"trend": "BULL_STACK" if i < 20 else "BEAR_STACK"},
            }
        )
    atlas = build_reaction_atlas(rows, minimum_samples=10)
    assert atlas["sample_count"] == 40
    assert atlas["year_min"] == 2012
    assert atlas["overall"]["historical_up_frequency_15m"] == 24 / 40
    assert atlas["execution_authority"] is False
    assert "not calibrated probabilities" in atlas["interpretation"]
