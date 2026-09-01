from datetime import datetime, timedelta, timezone

import pytest

from fx_scanner.config import load_project_config
from fx_scanner.macro import CurrencyMacroScore, MacroStatus
from fx_scanner.models import Bar
from fx_scanner.ranking import CurrencyStrength, PairRank
from fx_scanner.signal_producer import CTraderSignalProducer
from fx_scanner.storage.supabase_operational import (
    OperationalStoreUnavailable,
    SupabaseOperationalStore,
)

UTC = timezone.utc
AS_OF = datetime(2026, 9, 2, 0, 0, tzinfo=UTC)


class Quote:
    def __init__(self, ts):
        self.bid = 1.1000
        self.ask = 1.1002
        self.timestamp = ts


class Feed:
    def __init__(self):
        self.calls = 0
        self.connected = 0

    def ensure_connected(self):
        self.connected += 1

    def quote(self, _symbol):
        return Quote(AS_OF)

    def historical_bars(self, symbol, timeframe, *, from_time, to_time, count):
        del from_time
        self.calls += 1
        seconds = {
            "M5": 300,
            "M15": 900,
            "H1": 3600,
            "H4": 14400,
            "D1": 86400,
        }[timeframe]
        start = to_time - timedelta(seconds=seconds * count)
        out = []
        for i in range(count):
            ts = start + timedelta(seconds=seconds * i)
            base = 1.0800 + i * 0.0002
            out.append(
                Bar(
                    symbol,
                    timeframe,
                    ts,
                    base,
                    base + 0.0005,
                    base - 0.0005,
                    base + 0.0002,
                    100 + i,
                    0.0002,
                    0.0002,
                )
            )
        return tuple(out)


class Store:
    def __init__(self):
        self.finished = []
        self.strength = []
        self.rankings = []
        self.signals = []

    def start_scanner_run(self, **_kwargs):
        return "00000000-0000-0000-0000-000000000014"

    def finish_scanner_run(self, run_id, **kwargs):
        self.finished.append((run_id, kwargs["status"]))

    def get_latest_currency_macro_states(self, currencies):
        raise AssertionError("macro reader should be replaced in this focused test")

    def write_currency_strength_rows(self, rows):
        self.strength.extend(rows)

    def write_pair_ranking_rows(self, rows):
        self.rankings.extend(rows)

    def write_signal_rows(self, rows):
        self.signals.extend(rows)


def _strength(cfg):
    currencies = sorted({p.base for p in cfg.pairs}.union({p.quote for p in cfg.pairs}))
    return {
        c: CurrencyStrength(c, 10.0 if c == "EUR" else 0.0, 1, 1, 1.0)
        for c in currencies
    }


def _macro(cfg):
    currencies = sorted({p.base for p in cfg.pairs}.union({p.quote for p in cfg.pairs}))
    return {
        c: CurrencyMacroScore(
            c,
            80.0 if c == "EUR" else 0.0,
            1.0,
            MacroStatus.AVAILABLE,
            (),
        )
        for c in currencies
    }


def test_producer_keeps_missing_external_guards_fail_closed(monkeypatch):
    cfg = load_project_config()
    feed = Feed()
    store = Store()
    producer = CTraderSignalProducer(
        cfg,
        feed,
        store,
        code_version="test-sha",
        sleeper=lambda _seconds: None,
        clock=lambda: AS_OF,
    )

    strengths = _strength(cfg)
    monkeypatch.setattr(
        producer,
        "_technical_strength",
        lambda _bars: (
            strengths,
            {
                "M15": strengths,
                "H1": strengths,
                "H4": strengths,
                "D1": strengths,
            },
        ),
    )
    monkeypatch.setattr(producer, "_macro_scores", lambda **_kwargs: (_macro(cfg), ()))

    one_rank = PairRank(
        symbol="EURUSD",
        direction="LONG",
        relative_macro_edge=80.0,
        relative_technical_edge=10.0,
        cross_asset_edge=50.0,
        pair_edge=80.0,
        absolute_edge=80.0,
        coverage=1.0,
        missing_components=(),
        rank=1,
    )
    monkeypatch.setattr(
        "fx_scanner.signal_producer.rank_pairs",
        lambda *_args, **_kwargs: [one_rank],
    )

    report = producer.run_once()

    assert report.ranked_pairs == 1
    assert report.deep_candidates == 1
    assert report.signals_written == 1
    assert report.execution_ready == 0
    assert feed.calls == len(cfg.pairs) * len(cfg.strategy["mtf"]["required_timeframes"])
    assert store.finished[-1][1] == "COMPLETED"
    assert store.signals[0]["state"] == "NO_TRADE"
    assert "GUARD_INPUT_MISSING:NEWS_BLOCK" in store.signals[0]["active_guards"]
    assert "GUARD_INPUT_MISSING:DATA_QUALITY_BLOCK" in store.signals[0]["active_guards"]


class NeverWriteClient:
    def table(self, _name):
        raise AssertionError("unsafe EXECUTION_READY must be rejected before database I/O")


def test_storage_rejects_unsafe_execution_ready_before_io():
    store = SupabaseOperationalStore(
        "https://example.supabase.co",
        "secret",
        client=NeverWriteClient(),
    )
    with pytest.raises(OperationalStoreUnavailable, match="active guards"):
        store.write_signal_rows(
            [
                {
                    "state": "EXECUTION_READY",
                    "active_guards": ["NEWS_BLOCK"],
                    "final_score": 95.0,
                    "data_coverage": 0.95,
                }
            ]
        )


def test_stale_quote_prevents_symbol_from_reaching_analysis(monkeypatch):
    cfg = load_project_config()
    feed = Feed()
    store = Store()
    producer = CTraderSignalProducer(
        cfg,
        feed,
        store,
        code_version="test-sha",
        sleeper=lambda _seconds: None,
        clock=lambda: AS_OF,
    )
    feed.quote = lambda _symbol: Quote(AS_OF - timedelta(seconds=10))

    monkeypatch.setattr(producer, "_technical_strength", lambda _bars: ({}, {}))
    monkeypatch.setattr(producer, "_macro_scores", lambda **_kwargs: ({}, tuple()))

    report = producer.run_once()

    assert report.market_symbols == 0
    assert report.ranked_pairs == 0
    assert report.signals_written == 0
    assert report.execution_ready == 0
    assert len(report.skipped) == len(cfg.pairs)
    assert all(value.startswith("QUOTE_STALE:") for value in report.skipped.values())


def test_producer_quote_freshness_is_configurable_from_policy(monkeypatch):
    cfg = load_project_config()
    feed = Feed()
    store = Store()
    producer = CTraderSignalProducer(
        cfg,
        feed,
        store,
        code_version="test-sha",
        max_quote_age_seconds=12.0,
        sleeper=lambda _seconds: None,
        clock=lambda: AS_OF,
    )
    feed.quote = lambda _symbol: Quote(AS_OF - timedelta(seconds=10))
    monkeypatch.setattr(producer, "_technical_strength", lambda _bars: ({}, {}))
    monkeypatch.setattr(producer, "_macro_scores", lambda **_kwargs: ({}, tuple()))

    report = producer.run_once()

    assert report.market_symbols == len(cfg.pairs)
