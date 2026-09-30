from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import fx_scanner.demo_xau_structural_control_sampler_v303 as sampler


NOW = datetime(2026, 9, 30, 9, 30, tzinfo=UTC)


def _atlas(direction: str = "LONG") -> dict:
    source = {
        "low": 4167.34,
        "high": 4187.57,
        "distal": 4167.34 if direction == "LONG" else 4200.0,
        "zone_id": "source-zone",
        "timeframe": "H4",
        "status": "APPROACHING_PREPARE_ONLY",
        "direction": direction,
        "research_score": 59.29,
        "lifecycle": {
            "active": True,
            "invalidated_at": None,
        },
    }
    if direction == "LONG":
        target = 4194.22
    else:
        source.update({"low": 4180.0, "high": 4200.0, "distal": 4200.0})
        target = 4170.0
    return {
        "healthy": True,
        "observed_at": "2026-09-30T09:29:30+00:00",
        "details": {
            "evaluation": {
                "path_map": {
                    "active_path": {
                        "state": "SOURCE_ZONE_APPROACHING",
                        "reaction_direction": direction,
                        "source_zone": source,
                        "reaction_target": {
                            "role": "REACTION_TARGET",
                            "price": target,
                            "source": "OPPOSING_ZONE_PROXIMAL_FALLBACK",
                        },
                    }
                }
            }
        },
    }


def _v226(direction: str = "LONG", *, strict: bool = False) -> dict:
    entry = 4177.896 if direction == "LONG" else 4190.0
    return {
        "healthy": True,
        "observed_at": "2026-09-30T09:29:35+00:00",
        "details": {
            "evaluation": {
                "depth_entry_candidate": {
                    "direction": direction,
                    "entry_reference": entry,
                    "source_layer": "M15_NESTED_LOCATOR",
                    "display_status": "CONTEXT_ONLY_OUT_OF_SAMPLE",
                    "execution_authority": False,
                    "execution_influence": False,
                    "pre_touch_execution_eligible": strict,
                    "confirmation_execution_eligible": False,
                }
            }
        },
    }


def test_v303_builds_intact_control_geometry_from_v226_and_v182() -> None:
    geometry, reason = sampler._build_control_geometry(
        atlas_heartbeat=_atlas(),
        v226_heartbeat=_v226(),
        now=NOW,
    )

    assert reason == "CONTROL_GEOMETRY_READY"
    assert geometry["direction"] == "LONG"
    assert geometry["entry"] == 4177.896
    assert geometry["sl"] == 4167.34
    assert geometry["tp"] == 4194.22
    assert geometry["source_zone_id"] == "source-zone"
    assert geometry["execution_authority"] is False
    assert geometry["execution_influence"] == "DEMO_RESEARCH_CONTROL_ONLY"
    assert geometry["rr"] > 1.5


def test_v303_does_not_duplicate_candidate_owned_by_strict_lane() -> None:
    geometry, reason = sampler._build_control_geometry(
        atlas_heartbeat=_atlas(),
        v226_heartbeat=_v226(strict=True),
        now=NOW,
    )
    assert geometry == {}
    assert reason == "CANDIDATE_OWNED_BY_STRICT_LANE"


def test_v303_fails_closed_on_atlas_v226_direction_mismatch() -> None:
    geometry, reason = sampler._build_control_geometry(
        atlas_heartbeat=_atlas("SHORT"),
        v226_heartbeat=_v226("LONG"),
        now=NOW,
    )
    assert geometry == {}
    assert reason == "ATLAS_V226_DIRECTION_MISMATCH"


def test_v303_signal_id_is_deterministic_per_structural_signature() -> None:
    first = sampler.control_signal_id("LONG|zone|entry|stop|target")
    second = sampler.control_signal_id("LONG|zone|entry|stop|target")
    other = sampler.control_signal_id("SHORT|zone|entry|stop|target")
    assert first == second
    assert first != other


def test_v303_workflow_dashboard_and_xau_only_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (
        root / ".github" / "workflows" / "ctrader-demo-xau-execution-lane.yml"
    ).read_text()
    supervisor = (
        root / ".github" / "workflows" / "ctrader-demo-auto-supervisor.yml"
    ).read_text()
    dashboard = (root / "streamlit_app.py").read_text()
    source = (
        root / "src" / "fx_scanner" / "demo_xau_structural_control_sampler_v303.py"
    ).read_text()

    assert 'CTRADER_DEMO_XAU_STRUCTURAL_CONTROL_SAMPLER_ENABLED: "1"' in workflow
    assert "python -m fx_scanner.demo_xau_structural_control_sampler_v303" in workflow
    assert "demo_xau_structural_control_sampler_v303.py" in supervisor
    assert '"ctrader_demo_xau_structural_control_sampler_v303"' in dashboard
    assert "V303 Structural Control Research" in dashboard
    assert 'SYMBOL = "XAUUSD"' in source
    assert 'LOT = 0.01' in source
    assert 'MIN_RR = 1.0' in source
    assert "DEMO_STRUCTURAL_CONTROL_ONLY" in source
    assert "DEMO_RESEARCH_CONTROL_ONLY" in source
    assert 'build_broker_gateway(policy, (SYMBOL,), backend="CTRADER")' in source
    assert 'execution_authority": False' in source
