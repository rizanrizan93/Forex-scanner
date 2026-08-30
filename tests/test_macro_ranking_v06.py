from fx_scanner.config import load_project_config
from fx_scanner.macro import MacroStatus, relative_macro_edge, score_currency_macro
from fx_scanner.ranking import compute_currency_strength, rank_pairs


def _factors(**overrides):
    base = {
        "interest_rate": 80,
        "central_bank_bias": 60,
        "inflation": 40,
        "growth": 20,
        "labour": 10,
        "yield_momentum": 50,
        "risk_commodity": 0,
        "positioning": -10,
    }
    base.update(overrides)
    return base


def test_macro_missing_is_not_converted_to_neutral_zero():
    cfg = load_project_config()
    weights = cfg.macro["weights"]
    partial = _factors(positioning=None)
    result = score_currency_macro(
        "USD",
        partial,
        weights,
        minimum_coverage=cfg.macro["minimum_coverage"],
    )
    assert result.status == MacroStatus.PARTIAL
    assert result.score is not None
    assert result.coverage == 0.95
    assert "positioning" in result.missing_factors

    insufficient = {name: None for name in weights}
    insufficient["interest_rate"] = 80
    insufficient["central_bank_bias"] = 60
    blocked = score_currency_macro(
        "USD",
        insufficient,
        weights,
        minimum_coverage=cfg.macro["minimum_coverage"],
    )
    assert blocked.status == MacroStatus.PARTIAL
    assert blocked.score is None
    assert blocked.coverage == 0.45


def test_macro_invalid_factor_fails_closed():
    cfg = load_project_config()
    result = score_currency_macro(
        "EUR",
        _factors(inflation=150),
        cfg.macro["weights"],
        minimum_coverage=cfg.macro["minimum_coverage"],
    )
    assert result.status == MacroStatus.INVALID
    assert result.score is None


def test_relative_macro_edge_requires_both_numeric_scores():
    cfg = load_project_config()
    good = score_currency_macro("EUR", _factors(), cfg.macro["weights"])
    missing = score_currency_macro(
        "USD",
        {name: None for name in cfg.macro["weights"]},
        cfg.macro["weights"],
    )
    assert relative_macro_edge(good, missing) is None


def test_currency_strength_respects_base_quote_orientation():
    cfg = load_project_config()
    strength = compute_currency_strength(
        {
            "EURUSD": 80,
            "GBPUSD": 40,
            "USDJPY": -20,
        },
        cfg.pairs,
    )
    assert strength["EUR"].score == 80
    assert strength["GBP"].score == 40
    assert strength["USD"].contributing_pairs == 3
    assert strength["USD"].score < 0
    assert strength["JPY"].score > 0


def test_pair_ranking_combines_signed_macro_technical_and_cross_asset_edges():
    cfg = load_project_config()
    macro = {
        "EUR": 80,
        "USD": 0,
        "GBP": 20,
        "JPY": -20,
        "CHF": -10,
        "CAD": 0,
        "AUD": 10,
        "NZD": 5,
    }
    technical = {
        "EUR": 70,
        "USD": 0,
        "GBP": 20,
        "JPY": -30,
        "CHF": -10,
        "CAD": 0,
        "AUD": 10,
        "NZD": 5,
    }
    ranked = rank_pairs(
        cfg.pairs,
        macro_scores=macro,
        technical_strength=technical,
        cross_asset_edges={"EURUSD": 30},
    )
    eurusd = next(x for x in ranked if x.symbol == "EURUSD")
    assert eurusd.direction == "LONG"
    assert eurusd.pair_edge > 0
    assert eurusd.rank <= 3
    assert ranked == sorted(ranked, key=lambda x: (-x.absolute_edge, -x.coverage, x.symbol))


def test_missing_cross_asset_is_partial_not_neutral_zero():
    cfg = load_project_config()
    macro = {c: 0 for c in ("EUR","USD","GBP","JPY","CHF","CAD","AUD","NZD")}
    macro["EUR"] = 80
    technical = {c: 0 for c in macro}
    technical["EUR"] = 60
    ranked = rank_pairs(
        cfg.pairs,
        macro_scores=macro,
        technical_strength=technical,
        cross_asset_edges={},
    )
    eurusd = next(x for x in ranked if x.symbol == "EURUSD")
    assert eurusd.cross_asset_edge is None
    assert eurusd.coverage == 0.85
    assert eurusd.missing_components == ("cross_asset",)
