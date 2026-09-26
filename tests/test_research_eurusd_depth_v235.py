from pathlib import Path

from fx_scanner.research_eurusd_depth_v235_aggregate import ERAS, _headline

ROOT = Path(__file__).resolve().parents[1]


def test_v235_eras_match_existing_xau_research_contract() -> None:
    assert ERAS == {
        "2012_2018": (2012, 2018),
        "2019_2024": (2019, 2024),
        "2025_2026": (2025, 2026),
    }


def test_v235_headline_reports_depth_dispersion() -> None:
    report = {
        "H4": {
            "ALL": {
                "touches": 100,
                "hold_rate": 0.60,
                "hold_wilson_lower_95": 0.50,
                "depth_p25": 0.25,
                "depth_median": 0.40,
                "depth_p75": 0.55,
                "highest_hazard_bands_min_n": [
                    {
                        "band": "30-40%",
                        "hazard": 0.30,
                        "at_risk": 60,
                        "wilson_lower_95": 0.20,
                    }
                ],
            }
        }
    }
    row = _headline(report)["H4"]
    assert abs(row["depth_iqr"] - 0.30) < 1e-12
    assert row["highest_hazard_band"] == "30-40%"


def test_v235_workflow_is_full_history_and_shadow_only() -> None:
    workflow = (
        ROOT / ".github/workflows/research-eurusd-depth-v235.yml"
    ).read_text(encoding="utf-8")
    assert "2012" in workflow
    assert "2026" in workflow
    assert "research_eurusd_histdata_download_v235" in workflow
    assert "research_eurusd_depth_v235_year_runtime" in workflow
    assert "research_eurusd_depth_v235_aggregate" in workflow

    source = (
        ROOT / "src/fx_scanner/research_eurusd_depth_v235_year_runtime.py"
    ).read_text(encoding="utf-8")
    assert '"pair": "EURUSD"' in source
    assert '"policy_effect": "SHADOW_ONLY"' in source
    assert '"execution_authority": False' in source
    assert '"live_execution_enabled": False' in source
