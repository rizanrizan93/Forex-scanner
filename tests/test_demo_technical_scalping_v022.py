from fx_scanner.cli import (
    _apply_demo_execution_threshold,
    _apply_demo_technical_only_profile,
)
from fx_scanner.config import load_project_config
from fx_scanner.ranking import CurrencyStrength, PairRank, rank_pairs_technical_only
from fx_scanner.strategy import select_pair_candidates


def test_alternative_assets_are_in_20_instrument_universe():
    cfg = load_project_config()

    assert len(cfg.pairs) == 20
    assert cfg.pair_map["XAUUSD"].base == "XAU"
    assert cfg.pair_map["XAUUSD"].quote == "USD"
    assert cfg.pair_map["XAUUSD"].pip_size == 0.01
    assert cfg.pair_map["XTIUSD"].pip_size == 0.01
    assert cfg.pair_map["BTCUSD"].pip_size == 1.0
    assert cfg.pair_map["ETHUSD"].pip_size == 1.0
    assert cfg.pair_map["SOLUSD"].pip_size == 0.01


def test_demo_technical_profile_removes_macro_from_conviction_and_news_from_execution(monkeypatch):
    monkeypatch.setenv("CTRADER_DEMO_EXECUTION_CANDIDATE_MIN", "70")
    cfg = load_project_config()

    cfg, production_default = _apply_demo_execution_threshold(cfg)
    technical = _apply_demo_technical_only_profile(cfg)

    assert production_default == 90.0
    assert technical.scoring["states"]["execution_candidate_min"] == 70.0
    assert set(technical.scoring["execution_conviction"]) == {
        "htf_structure",
        "liquidity",
        "smc_structure",
        "displacement",
        "session",
        "execution_quality",
    }
    assert sum(technical.scoring["execution_conviction"].values()) == 100.0
    assert "relative_macro" not in technical.scoring["execution_conviction"]
    assert "cross_asset" not in technical.scoring["execution_conviction"]
    assert "positioning" not in technical.scoring["execution_conviction"]
    assert "NEWS_BLOCK" not in technical.scoring["hard_guards"]
    for guard in (
        "SPREAD_BLOCK",
        "VOLATILITY_BLOCK",
        "CORRELATION_BLOCK",
        "RISK_BLOCK",
        "STALE_SIGNAL",
        "CHASE_BLOCK",
        "RR_BLOCK",
        "STRUCTURE_INVALID",
        "DATA_QUALITY_BLOCK",
    ):
        assert guard in technical.scoring["hard_guards"]

    # Canonical config remains untouched.
    canonical = load_project_config()
    assert canonical.scoring["states"]["execution_candidate_min"] == 90
    assert "relative_macro" in canonical.scoring["execution_conviction"]
    assert "NEWS_BLOCK" in canonical.scoring["hard_guards"]


def test_technical_only_ranking_can_rank_xauusd_without_macro():
    cfg = load_project_config()
    currencies = {pair.base for pair in cfg.pairs} | {pair.quote for pair in cfg.pairs}
    technical = {
        currency: CurrencyStrength(
            currency=currency,
            score=80.0 if currency == "XAU" else 0.0,
            contributing_pairs=1,
            expected_pairs=1,
            coverage=1.0,
        )
        for currency in currencies
    }

    ranked = rank_pairs_technical_only(
        cfg.pairs,
        technical_strength=technical,
        minimum_coverage=0.80,
    )
    xau = next(item for item in ranked if item.symbol == "XAUUSD")

    assert xau.direction == "LONG"
    assert xau.relative_macro_edge == 0.0
    assert xau.relative_technical_edge == 80.0
    assert xau.pair_edge == 40.0
    assert xau.coverage == 1.0
    assert xau.missing_components == ()


def test_technical_candidate_selection_uses_technical_edge_not_macro_edge():
    candidate = PairRank(
        symbol="XAUUSD",
        direction="LONG",
        relative_macro_edge=0.0,
        relative_technical_edge=80.0,
        cross_asset_edge=None,
        pair_edge=40.0,
        absolute_edge=40.0,
        coverage=1.0,
        missing_components=(),
        rank=1,
    )

    selected = select_pair_candidates(
        [candidate],
        macro_compatible_top=8,
        deep_analysis_top=5,
        compatibility_mode="TECHNICAL",
    )

    assert selected.deep_analysis == (candidate,)
