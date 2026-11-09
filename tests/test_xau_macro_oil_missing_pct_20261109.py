"""Regression for Streamlit oil-context crash seen in Nov 9 logs.

A DIA spot quote can have fresh=True but pct=None before a 10-20 min
baseline is available; never compare it against zero or vote on inflation.
"""
from datetime import UTC, datetime, timedelta

from fx_scanner.xau_macro_risk_monitor import _oil_direction_caption

NOW = datetime(2026, 11, 9, 4, 30, tzinfo=UTC)


def quote(pct, *, basis="perubahan spot 10–20 menit", source="DIA spot",
          fresh=True, time=NOW):
    return {
        "value": 76.42, "pct": pct, "source": source, "fresh": fresh,
        "observed": time.isoformat(), "basis": basis,
        "instrument_type": "SPOT",
    }


def test_crash_reproduction_both_fresh_without_pct_is_safe():
    message = _oil_direction_caption(quote(None), quote(None), now=NOW)
    assert "baseline" in message
    assert "arah tidak dinilai" in message


def test_one_null_pct_does_not_crash_or_generate_inflation_vote():
    assert "arah tidak dinilai" in _oil_direction_caption(quote(0.5), quote(None), now=NOW)


def test_both_valid_and_same_basis_positive():
    assert "Energi naik" in _oil_direction_caption(quote(0.8), quote(0.3), now=NOW)


def test_both_valid_and_same_basis_negative():
    assert "Energi turun" in _oil_direction_caption(quote(-0.3), quote(-0.6), now=NOW)


def test_mixed_and_zero_is_not_assumed_directional():
    assert "mixed/flat" in _oil_direction_caption(quote(0.0), quote(0.6), now=NOW)


def test_nonfinite_pct_not_a_valid_oil_vote():
    assert "arah tidak dinilai" in _oil_direction_caption(quote(float("nan")), quote(0.2), now=NOW)
    assert "arah tidak dinilai" in _oil_direction_caption(quote(float("inf")), quote(0.2), now=NOW)


def test_stale_or_daily_data_does_not_vote_even_with_fresh_flag():
    stale = quote(1.2, time=NOW - timedelta(minutes=8))
    assert "belum segar" in _oil_direction_caption(stale, quote(0.2), now=NOW)
    daily = quote(1.2, source="FRED (spot harian)")
    assert "belum segar" in _oil_direction_caption(daily, quote(0.2), now=NOW)


def test_basis_mismatch_not_combined():
    assert "basis berbeda" in _oil_direction_caption(
        quote(0.3), quote(0.4, basis="penutupan kemarin"), now=NOW,
    )


def test_missing_quotes_not_a_vote():
    assert "belum lengkap" in _oil_direction_caption(None, quote(1.0), now=NOW)
