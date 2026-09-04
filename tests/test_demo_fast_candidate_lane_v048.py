from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fx_scanner.config import PairSpec, ProjectConfig
from fx_scanner.demo_fast_candidate_producer import (
    latest_discovery_rankings,
    recent_candidate_symbols,
)

UTC = timezone.utc


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self.rows = list(rows)

    def select(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, value):
        self.rows = self.rows[: int(value)]
        return self

    def execute(self):
        return _Result(self.rows)


class _Client:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return _Query(self.tables[name])


class _Store:
    def __init__(self, tables):
        self.client = _Client(tables)


def _cfg() -> ProjectConfig:
    pairs = (
        PairSpec("EURUSD", "EUR", "USD", 0.0001, "A"),
        PairSpec("GBPUSD", "GBP", "USD", 0.0001, "A"),
        PairSpec("USDJPY", "USD", "JPY", 0.01, "A"),
    )
    return ProjectConfig(
        pairs=pairs,
        timeframes={},
        risk={},
        scoring={},
        sessions={},
        macro={},
        providers={},
        strategy={},
        validation={},
    )


def test_recent_candidates_are_bounded_fresh_and_state_prioritized():
    now = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
    rows = [
        {
            "observed_at": (now - timedelta(minutes=3)).isoformat(),
            "symbol": "EURUSD",
            "state": "ARMED",
            "final_score": 62.0,
        },
        {
            "observed_at": (now - timedelta(minutes=2)).isoformat(),
            "symbol": "GBPUSD",
            "state": "EXECUTION_READY",
            "final_score": 51.0,
        },
        {
            "observed_at": (now - timedelta(minutes=1)).isoformat(),
            "symbol": "USDJPY",
            "state": "NO_TRADE",
            "final_score": 99.0,
        },
        {
            "observed_at": (now - timedelta(minutes=60)).isoformat(),
            "symbol": "USDJPY",
            "state": "EXECUTION_READY",
            "final_score": 99.0,
        },
    ]
    store = _Store({"signals": rows})

    symbols = recent_candidate_symbols(
        store,
        _cfg(),
        now=now,
        lookback_minutes=45,
        max_symbols=2,
    )

    assert symbols == ("GBPUSD", "EURUSD")


def test_fast_lane_preserves_latest_full_universe_direction_and_rank():
    now = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
    rows = [
        {
            "run_id": "slow-new",
            "observed_at": (now - timedelta(minutes=4)).isoformat(),
            "symbol": "EURUSD",
            "direction": "SHORT",
            "technical_edge": -84.0,
            "pair_opportunity_score": 42.0,
            "rank": 2,
            "coverage": 1.0,
        },
        {
            "run_id": "slow-old",
            "observed_at": (now - timedelta(minutes=9)).isoformat(),
            "symbol": "EURUSD",
            "direction": "LONG",
            "technical_edge": 70.0,
            "pair_opportunity_score": 35.0,
            "rank": 3,
            "coverage": 1.0,
        },
        {
            "run_id": "slow-new",
            "observed_at": (now - timedelta(minutes=4)).isoformat(),
            "symbol": "GBPUSD",
            "direction": "LONG",
            "technical_edge": 92.0,
            "pair_opportunity_score": 46.0,
            "rank": 1,
            "coverage": 0.95,
        },
        {
            "run_id": "stale",
            "observed_at": (now - timedelta(minutes=30)).isoformat(),
            "symbol": "USDJPY",
            "direction": "SHORT",
            "technical_edge": -60.0,
            "pair_opportunity_score": 30.0,
            "rank": 4,
            "coverage": 1.0,
        },
    ]
    store = _Store({"pair_rankings": rows})

    ranks = latest_discovery_rankings(
        store,
        _cfg(),
        ("EURUSD", "GBPUSD", "USDJPY"),
        now=now,
        max_age_minutes=20,
    )

    assert [item.symbol for item in ranks] == ["EURUSD", "GBPUSD"]
    assert ranks[0].direction == "SHORT"
    assert ranks[0].pair_edge == -42.0
    assert ranks[0].rank == 2
    assert ranks[1].direction == "LONG"
    assert ranks[1].pair_edge == 46.0


def test_fast_lane_rejects_low_coverage_discovery_rank():
    now = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
    store = _Store(
        {
            "pair_rankings": [
                {
                    "run_id": "slow",
                    "observed_at": (now - timedelta(minutes=2)).isoformat(),
                    "symbol": "EURUSD",
                    "direction": "LONG",
                    "technical_edge": 80.0,
                    "pair_opportunity_score": 40.0,
                    "rank": 1,
                    "coverage": 0.79,
                }
            ]
        }
    )

    ranks = latest_discovery_rankings(
        store,
        _cfg(),
        ("EURUSD",),
        now=now,
        max_age_minutes=20,
    )

    assert ranks == ()
