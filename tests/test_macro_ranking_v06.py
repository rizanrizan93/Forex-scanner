import pytest

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
    assert strength["USD"].expected_pairs == 8
    assert strength["USD"].coverage == 3 / 7
    assert strength["EUR"].coverage == 1 / 5
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
    assert eurusd.coverage == pytest.approx(0.85)
    assert eurusd.missing_components == ("cross_asset",)


def test_boolean_macro_and_ranking_evidence_fail_closed():
    from fx_scanner.exceptions import DataContractError

    cfg = load_project_config()
    factors = _factors(inflation=True)
    result = score_currency_macro("USD", factors, cfg.macro["weights"])
    assert result.status == MacroStatus.INVALID
    assert result.score is None

    with pytest.raises(DataContractError, match="boolean momentum"):
        compute_currency_strength({"EURUSD": True}, cfg.pairs)

    macro = {c: 0 for c in ("EUR","USD","GBP","JPY","CHF","CAD","AUD","NZD")}
    technical = {c: 0 for c in macro}
    with pytest.raises(DataContractError, match="boolean cross-asset"):
        rank_pairs(
            cfg.pairs,
            macro_scores=macro,
            technical_strength=technical,
            cross_asset_edges={"EURUSD": True},
        )


def test_pair_rank_coverage_propagates_partial_macro_evidence():
    cfg = load_project_config()
    partial_factors = _factors(positioning=None)
    macro = {
        currency: score_currency_macro(
            currency,
            partial_factors,
            cfg.macro["weights"],
            minimum_coverage=cfg.macro["minimum_coverage"],
        )
        for currency in ("EUR","USD","GBP","JPY","CHF","CAD","AUD","NZD")
    }
    # Give EUR a stronger macro value without changing its 95% coverage.
    eur_factors = _factors(positioning=None, interest_rate=100, central_bank_bias=100)
    macro["EUR"] = score_currency_macro(
        "EUR",
        eur_factors,
        cfg.macro["weights"],
        minimum_coverage=cfg.macro["minimum_coverage"],
    )
    technical = {currency: 0 for currency in macro}
    technical["EUR"] = 60

    ranked = rank_pairs(
        cfg.pairs,
        macro_scores=macro,
        technical_strength=technical,
        cross_asset_edges={},
        minimum_coverage=0.80,
    )
    eurusd = next(x for x in ranked if x.symbol == "EURUSD")
    assert eurusd.coverage == 0.55 * 0.95 + 0.30
    assert eurusd.coverage < 0.85
    assert eurusd.missing_components == ("cross_asset",)


def test_low_currency_strength_coverage_can_remove_pair_from_ranking():
    cfg = load_project_config()
    strength = compute_currency_strength({"EURUSD": 80}, cfg.pairs)
    macro = {c: 0 for c in ("EUR","USD","GBP","JPY","CHF","CAD","AUD","NZD")}
    ranked = rank_pairs(
        cfg.pairs,
        macro_scores=macro,
        technical_strength=strength,
        cross_asset_edges={"EURUSD": 0},
        minimum_coverage=0.80,
    )
    assert all(x.symbol != "EURUSD" for x in ranked)
