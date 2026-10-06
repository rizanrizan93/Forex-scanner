from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _assert_bootstrap_precedes_fx_import(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    bootstrap = text.find("sys.path.insert")
    fx_import = text.find("from fx_scanner")
    assert bootstrap >= 0, f"missing src bootstrap in {path}"
    assert fx_import >= 0, f"missing fx_scanner import in {path}"
    assert bootstrap < fx_import, f"fx_scanner imported before src bootstrap in {path}"


def test_main_bootstraps_src_before_fx_scanner_import():
    _assert_bootstrap_precedes_fx_import(ROOT / "main.py")


def test_multipage_files_bootstrap_src_before_fx_scanner_import():
    pages = [
        ROOT / "pages" / "0_Pusat_Keputusan_XAUUSD.py",
        ROOT / "pages" / "1_Demand_Tiers.py",
        ROOT / "pages" / "2_US10Y_Regime_Timing.py",
    ]
    for page in pages:
        _assert_bootstrap_precedes_fx_import(page)
