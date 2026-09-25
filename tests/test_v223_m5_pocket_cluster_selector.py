from datetime import UTC, datetime
from pathlib import Path

from fx_scanner.demo_xau_v223_m5_pocket_cluster_selector import (
    cluster_pocket_family,
    select_clusters,
)

ROOT = Path(__file__).resolve().parents[1]


def _pocket(
    seq: int,
    low: float,
    high: float,
    mapped: str,
    *,
    quality: float = 50.0,
    timing: str = "MOVE_STARTED_WAIT_RETEST",
) -> dict:
    return {
        "sequence": seq,
        "direction": "SHORT",
        "low": low,
        "high": high,
        "mapped_at": mapped,
        "quality_score_research": quality,
        "timing_state": timing,
        "signal_key": f"p{seq}",
    }


def test_v223_clusters_near_overlapping_pockets_into_stable_micro_area() -> None:
    rows = [
        _pocket(1, 4303.11, 4304.68, "2026-09-25T12:10:03+00:00"),
        _pocket(2, 4303.71, 4304.88, "2026-09-25T12:16:40+00:00"),
    ]
    clusters = cluster_pocket_family(rows, atr_points=16.0)
    assert len(clusters) == 1
    assert len(clusters[0]) == 2


def test_v223_preserves_union_and_consensus_core() -> None:
    evaluation = {
        "direction": "SHORT",
        "current_price_reference": 4300.0,
        "parent_context": {"atr_points": 16.0},
        "family": [
            _pocket(1, 4303.11, 4304.68, "2026-09-25T12:10:03+00:00", quality=50),
            _pocket(2, 4303.71, 4304.88, "2026-09-25T12:16:40+00:00", quality=55),
        ],
    }
    result = select_clusters(
        evaluation,
        now=datetime(2026, 9, 25, 12, 20, tzinfo=UTC),
    )
    cluster = result["clusters"][0]
    assert cluster["union_zone"] == {"low": 4303.11, "high": 4304.88}
    assert cluster["consensus_core"] == {"low": 4303.71, "high": 4304.68}
    assert cluster["has_consensus_core"] is True
    assert result["primary_cluster"]["cluster_id"] == cluster["cluster_id"]
    assert result["execution_authority"] is False


def test_v223_does_not_select_all_late_cluster_as_primary_first_entry() -> None:
    evaluation = {
        "direction": "SHORT",
        "current_price_reference": 4300.0,
        "parent_context": {"atr_points": 16.0},
        "family": [
            _pocket(
                1,
                4312.59,
                4315.82,
                "2026-09-25T11:15:21+00:00",
                quality=47.0,
                timing="LATE_FOR_FIRST_ENTRY_WAIT_RETEST",
            ),
        ],
    }
    result = select_clusters(
        evaluation,
        now=datetime(2026, 9, 25, 12, 0, tzinfo=UTC),
    )
    assert result["primary_cluster"] == {}
    assert len(result["retest_only_clusters"]) == 1
    assert result["retest_only_clusters"][0]["role"] == "RETEST_ONLY_CLUSTER"


def test_v223_workflow_and_dashboard_are_shadow_only() -> None:
    workflow = (ROOT / ".github/workflows/ctrader-demo-maintenance-pipeline.yml").read_text()
    assert "python -m fx_scanner.demo_xau_v223_m5_pocket_cluster_selector" in workflow
    assert workflow.index("demo_xau_v222_m5_pocket_quality") < workflow.index(
        "demo_xau_v223_m5_pocket_cluster_selector"
    )

    dashboard = (ROOT / "streamlit_app.py").read_text()
    assert "V223 — Primary M5 Pocket Cluster" in dashboard
    assert "Consensus core" in dashboard
    assert "V223 tetap shadow-only" in dashboard
