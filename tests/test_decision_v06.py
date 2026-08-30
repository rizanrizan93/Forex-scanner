from datetime import datetime, timezone

from fx_scanner.config import load_project_config
from fx_scanner.decision import build_decision
from fx_scanner.models import SignalState
from fx_scanner.ranking import PairRank
from fx_scanner.scoring import score_with_state

UTC = timezone.utc


def rank():
    return PairRank(
        symbol="EURUSD",
        direction="LONG",
        relative_macro_edge=80,
        relative_technical_edge=60,
        cross_asset_edge=20,
        pair_edge=44.0,
        absolute_edge=44.0,
        coverage=1.0,
        missing_components=(),
        rank=1,
    )


def components(value=92):
    cfg = load_project_config()
    return {name: value for name in cfg.scoring["execution_conviction"]}


def test_execution_ready_requires_score_coverage_and_clear_guards():
    cfg = load_project_config()
    result = score_with_state(
        components(92),
        cfg.scoring["execution_conviction"],
        cfg.scoring["states"],
        hard_guards_clear=True,
    )
    assert result.score == 92
    assert result.coverage == 1
    assert result.state == SignalState.EXECUTION_READY


def test_hard_guard_forces_no_trade_even_with_high_score():
    cfg = load_project_config()
    decision = build_decision(
        rank=rank(),
        timestamp=datetime(2026, 8, 28, 10, tzinfo=UTC),
        conviction_components=components(99),
        conviction_weights=cfg.scoring["execution_conviction"],
        thresholds=cfg.scoring["states"],
        guard_flags={name: name == "NEWS_BLOCK" for name in cfg.scoring["hard_guards"]},
        required_guards=cfg.scoring["hard_guards"],
    )
    assert decision.conviction_score == 99
    assert decision.state == SignalState.NO_TRADE
    assert decision.guards == ("NEWS_BLOCK",)


def test_low_evidence_coverage_fails_closed_without_fake_neutral_values():
    cfg = load_project_config()
    values = components(95)
    values["relative_macro"] = None
    values["htf_structure"] = None
    values["liquidity"] = None
    decision = build_decision(
        rank=rank(),
        timestamp=datetime(2026, 8, 28, 10, tzinfo=UTC),
        conviction_components=values,
        conviction_weights=cfg.scoring["execution_conviction"],
        thresholds=cfg.scoring["states"],
        guard_flags={name: False for name in cfg.scoring["hard_guards"]},
        required_guards=cfg.scoring["hard_guards"],
        minimum_coverage=0.80,
    )
    assert decision.coverage < 0.80
    assert decision.conviction_score is None
    assert decision.state == SignalState.NO_TRADE
    assert set(decision.missing_components) == {"relative_macro", "htf_structure", "liquidity"}


def test_missing_guard_input_fails_closed():
    cfg = load_project_config()
    flags = {name: False for name in cfg.scoring["hard_guards"] if name != "NEWS_BLOCK"}
    decision = build_decision(
        rank=rank(),
        timestamp=datetime(2026, 8, 28, 10, tzinfo=UTC),
        conviction_components=components(99),
        conviction_weights=cfg.scoring["execution_conviction"],
        thresholds=cfg.scoring["states"],
        guard_flags=flags,
        required_guards=cfg.scoring["hard_guards"],
    )
    assert decision.state == SignalState.NO_TRADE
    assert "GUARD_INPUT_MISSING:NEWS_BLOCK" in decision.guards


def test_neutral_pair_can_never_be_execution_ready():
    cfg = load_project_config()
    neutral = PairRank(
        symbol="EURUSD",
        direction="NEUTRAL",
        relative_macro_edge=0,
        relative_technical_edge=0,
        cross_asset_edge=0,
        pair_edge=0,
        absolute_edge=0,
        coverage=1.0,
        missing_components=(),
        rank=1,
    )
    decision = build_decision(
        rank=neutral,
        timestamp=datetime(2026, 8, 28, 10, tzinfo=UTC),
        conviction_components=components(100),
        conviction_weights=cfg.scoring["execution_conviction"],
        thresholds=cfg.scoring["states"],
        guard_flags={name: False for name in cfg.scoring["hard_guards"]},
        required_guards=cfg.scoring["hard_guards"],
    )
    assert decision.state == SignalState.NO_TRADE
    assert "PAIR_DIRECTION_NEUTRAL" in decision.guards


def test_low_pair_coverage_blocks_high_conviction():
    cfg = load_project_config()
    partial = PairRank(
        symbol="EURUSD",
        direction="LONG",
        relative_macro_edge=80,
        relative_technical_edge=60,
        cross_asset_edge=None,
        pair_edge=40,
        absolute_edge=40,
        coverage=0.80,
        missing_components=("cross_asset",),
        rank=1,
    )
    decision = build_decision(
        rank=partial,
        timestamp=datetime(2026, 8, 28, 10, tzinfo=UTC),
        conviction_components=components(100),
        conviction_weights=cfg.scoring["execution_conviction"],
        thresholds=cfg.scoring["states"],
        guard_flags={name: False for name in cfg.scoring["hard_guards"]},
        required_guards=cfg.scoring["hard_guards"],
        minimum_pair_coverage=0.85,
    )
    assert decision.state == SignalState.NO_TRADE
    assert "PAIR_COVERAGE_BLOCK" in decision.guards
