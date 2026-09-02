import pytest

from fx_scanner.config import PairSpec
from fx_scanner.macro import CurrencyMacroScore, MacroStatus
from fx_scanner.ranking import CurrencyStrength, rank_pairs


PAIR = PairSpec("EURUSD", "EUR", "USD", 0.0001, "A")


def macro(currency, score):
    return CurrencyMacroScore(
        currency=currency,
        score=score,
        coverage=0.70,
        status=MacroStatus.PARTIAL,
        missing_factors=("central_bank_bias", "positioning", "risk_commodity"),
    )


def strength(currency, score, *, contributing=1, expected=1):
    return CurrencyStrength(
        currency=currency,
        score=score,
        contributing_pairs=contributing,
        expected_pairs=expected,
        coverage=contributing / expected,
    )


def test_rank_coverage_normalizes_over_observed_components_without_lowering_gate():
    ranked = rank_pairs(
        [PAIR],
        macro_scores={"EUR": macro("EUR", 50.0), "USD": macro("USD", -50.0)},
        technical_strength={
            "EUR": strength("EUR", 30.0),
            "USD": strength("USD", -30.0),
        },
        cross_asset_edges={},
        minimum_coverage=0.80,
    )

    assert len(ranked) == 1
    assert ranked[0].coverage == pytest.approx(0.55 * 0.70 + 0.30)
    assert (ranked[0].coverage / 0.85) >= 0.80
    assert ranked[0].missing_components == ("cross_asset",)


def test_rank_coverage_still_rejects_insufficient_observed_evidence():
    ranked = rank_pairs(
        [PAIR],
        macro_scores={"EUR": macro("EUR", 50.0), "USD": macro("USD", -50.0)},
        technical_strength={
            "EUR": strength("EUR", 30.0, contributing=3, expected=4),
            "USD": strength("USD", -30.0, contributing=3, expected=4),
        },
        cross_asset_edges={},
        minimum_coverage=0.80,
    )

    assert ranked == []


def test_rank_coverage_with_cross_asset_uses_full_weight_denominator():
    ranked = rank_pairs(
        [PAIR],
        macro_scores={"EUR": macro("EUR", 50.0), "USD": macro("USD", -50.0)},
        technical_strength={
            "EUR": strength("EUR", 30.0),
            "USD": strength("USD", -30.0),
        },
        cross_asset_edges={"EURUSD": 20.0},
        minimum_coverage=0.80,
    )

    assert len(ranked) == 1
    assert ranked[0].coverage == pytest.approx(0.55 * 0.70 + 0.30 + 0.15)
    assert ranked[0].missing_components == ()
