from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from fx_scanner.research_xau_event_conditioning_v193 import (
    event_conditioning,
    resample_ohlc,
)
from fx_scanner.research_xau_event_supplement_v193 import (
    _month_ranges,
    merge_event_corpora,
    parse_forex_factory_html,
)
from fx_scanner.research_xau_event_reaction_v193 import HistoricalEvent


def test_month_ranges_are_bounded_and_cover_span():
    rows = _month_ranges(date(2025, 4, 8), date(2025, 6, 2))
    assert rows == (
        (date(2025, 4, 8), date(2025, 4, 30)),
        (date(2025, 5, 1), date(2025, 5, 31)),
        (date(2025, 6, 1), date(2025, 6, 2)),
    )


def test_forex_factory_html_parser_preserves_simultaneous_time():
    pytest.importorskip("bs4")
    html = b"""
    <div>Calendar Time Zone: Europe/London (GMT +1)</div>
    <table>
      <tr class="calendar__row">
        <td class="calendar__date">Thu Sep 24</td>
        <td class="calendar__time">1:30pm</td>
        <td class="calendar__currency">USD</td>
        <td class="calendar__impact"><span title="High Impact Expected"></span></td>
        <td class="calendar__event">Core PCE Price Index m/m</td>
        <td class="calendar__actual">0.3%</td>
        <td class="calendar__forecast">0.2%</td>
        <td class="calendar__previous">0.2%</td>
      </tr>
      <tr class="calendar__row">
        <td class="calendar__date"></td>
        <td class="calendar__time"></td>
        <td class="calendar__currency">USD</td>
        <td class="calendar__impact"><span title="Medium Impact Expected"></span></td>
        <td class="calendar__event">Unemployment Claims</td>
        <td class="calendar__actual">201K</td>
        <td class="calendar__forecast">200K</td>
        <td class="calendar__previous">196K</td>
      </tr>
    </table>
    """
    rows = parse_forex_factory_html(
        html,
        year_hint=2026,
        source_url="https://www.forexfactory.com/calendar?range=sep24.2026-sep24.2026",
    )
    assert len(rows) == 2
    assert rows[0].scheduled_at == rows[1].scheduled_at
    assert rows[0].scheduled_at == datetime(2026, 9, 24, 12, 30, tzinfo=UTC)
    assert rows[0].family == "PCE"
    assert rows[1].family == "JOBLESS_CLAIMS"


def test_merge_prefers_pinned_archive_over_supplement():
    at = datetime(2025, 4, 7, 12, 30, tzinfo=UTC)
    supplement = HistoricalEvent(
        "supp",
        at,
        "CPI m/m",
        "CPI",
        "HIGH",
        "FF",
        "SECONDARY_CURRENT_PAGE",
        0.3,
        0.2,
        0.1,
    )
    archive = HistoricalEvent(
        "archive",
        at,
        "CPI m/m",
        "CPI",
        "HIGH",
        "HF",
        "SECONDARY_ARCHIVE",
        0.3,
        0.2,
        0.1,
    )
    merged = merge_event_corpora((archive,), (supplement,))
    assert len(merged) == 1
    assert merged[0].event_id == "archive"


def _m1_frame(days: int = 5) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    times = pd.date_range(start, periods=days * 24 * 60, freq="1min", tz="UTC")
    base = pd.Series(range(len(times)), dtype=float) * 0.001 + 2000.0
    return pd.DataFrame(
        {
            "timestamp": times,
            "open": base,
            "high": base + 0.15,
            "low": base - 0.10,
            "close": base + 0.05,
        }
    )


def test_resample_and_conditioning_are_shadow_only():
    frame = _m1_frame(5)
    m15 = resample_ohlc(frame, "15min")
    assert len(m15) >= 400
    at = frame["timestamp"].iloc[-1].to_pydatetime()
    out = event_conditioning(frame, event_at=at)
    assert out["state"] == "AVAILABLE"
    assert "H1" in out["mtf"]
    assert "H4" in out["mtf"]
    assert out["execution_authority"] is False
    assert out["supply_demand"]["execution_authority"] is False


def test_market_structure_only_mode_defers_supply_demand():
    frame = _m1_frame(5)
    at = frame["timestamp"].iloc[-1].to_pydatetime()
    out = event_conditioning(
        frame,
        event_at=at,
        include_supply_demand=False,
    )
    assert out["state"] == "AVAILABLE"
    assert out["supply_demand"]["state"] == "DEFERRED_POST_WALK_FORWARD"
    assert out["execution_authority"] is False


def test_forex_factory_parser_uses_page_declared_timezone_not_hardcoded_london():
    pytest.importorskip("bs4")
    html = b"""
    <div>Calendar Time Zone: America/Los_Angeles (GMT -7)</div>
    <table>
      <tr class="calendar__row">
        <td class="calendar__date">Fri Sep 11</td>
        <td class="calendar__time">5:30am</td>
        <td class="calendar__currency">USD</td>
        <td class="calendar__impact"><span title="High Impact Expected"></span></td>
        <td class="calendar__event">Core CPI m/m</td>
        <td class="calendar__actual">0.4%</td>
        <td class="calendar__forecast">0.3%</td>
        <td class="calendar__previous">0.2%</td>
      </tr>
    </table>
    """
    rows = parse_forex_factory_html(
        html,
        year_hint=2026,
        source_url="https://www.forexfactory.com/calendar?range=sep11.2026-sep11.2026",
    )
    assert len(rows) == 1
    # 05:30 PDT (UTC-7) is 12:30 UTC, matching the official 08:30 ET release.
    assert rows[0].scheduled_at == datetime(2026, 9, 11, 12, 30, tzinfo=UTC)


def test_forex_factory_parser_fails_closed_without_explicit_page_timezone():
    pytest.importorskip("bs4")
    html = b"""
    <table>
      <tr class="calendar__row">
        <td class="calendar__date">Fri Sep 11</td>
        <td class="calendar__time">5:30am</td>
        <td class="calendar__currency">USD</td>
        <td class="calendar__impact"><span title="High Impact Expected"></span></td>
        <td class="calendar__event">Core CPI m/m</td>
      </tr>
    </table>
    """
    with pytest.raises(RuntimeError, match="timezone"):
        parse_forex_factory_html(
            html,
            year_hint=2026,
            source_url="https://www.forexfactory.com/calendar",
        )


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("America/New York", "America/New_York"),
        ("America/Los Angeles", "America/Los_Angeles"),
        ("America/Phoenix", "America/Phoenix"),
    ],
)
def test_forex_factory_timezone_label_normalization(label, expected):
    pytest.importorskip("bs4")
    from bs4 import BeautifulSoup
    from fx_scanner.research_xau_event_supplement_v193 import _calendar_timezone_name

    soup = BeautifulSoup(
        f"<div>Calendar Time Zone: {label} (GMT -7)</div>",
        "html.parser",
    )
    assert _calendar_timezone_name(soup) == expected
