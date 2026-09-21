from datetime import date, datetime, timezone

from fx_scanner.research_xau_v137_cftc_positioning_forensic_v138 import (
    CFTC_PUBLICATION_LAG_DAYS,
    DIAGNOSTIC_ONLY,
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    CotAsof,
    build_cot_rows,
)


def _raw(d, oi, long, short):
    return {
        "report_date": d,
        "open_interest": oi,
        "managed_money_long": long,
        "managed_money_short": short,
        "producer_long": 1,
        "producer_short": 1,
        "swap_long": 1,
        "swap_short": 1,
    }


def test_v138_is_forensic_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True
    assert CFTC_PUBLICATION_LAG_DAYS == 7


def test_cot_asof_is_conservative_and_uses_four_report_delta():
    raw = [
        _raw(date(2026, 1, 6), 100, 60, 20),
        _raw(date(2026, 1, 13), 105, 62, 20),
        _raw(date(2026, 1, 20), 110, 64, 20),
        _raw(date(2026, 1, 27), 115, 66, 20),
        _raw(date(2026, 2, 3), 120, 70, 20),
    ]
    rows = build_cot_rows(raw)
    assert rows[-1].mm_net_delta4 == (70 - 20) - (60 - 20)
    lookup = CotAsof(rows)

    before_publication = datetime(2026, 2, 9, 23, 59, tzinfo=timezone.utc)
    assert lookup.row(before_publication).report_date == date(2026, 1, 27)

    after_conservative_publication = datetime(2026, 2, 10, 0, 0, tzinfo=timezone.utc)
    assert lookup.row(after_conservative_publication).report_date == date(2026, 2, 3)
