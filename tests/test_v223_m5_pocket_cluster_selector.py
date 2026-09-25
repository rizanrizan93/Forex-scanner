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




def test_v223_splits_transitive_chain_when_union_span_exceeds_micro_wave_bound() -> None:
    rows = [
        _pocket(1, 4301.60, 4308.13, "2026-09-25T10:20:28+00:00"),
        _pocket(2, 4305.13, 4309.00, "2026-09-25T10:27:17+00:00"),
        _pocket(3, 4306.17, 4309.63, "2026-09-25T10:34:14+00:00"),
        _pocket(4, 4309.14, 4311.73, "2026-09-25T11:01:15+00:00"),
        _pocket(5, 4310.40, 4311.93, "2026-09-25T11:08:18+00:00"),
        _pocket(
            6,
            4312.59,
            4315.82,
            "2026-09-25T11:15:21+00:00",
            timing="LATE_FOR_FIRST_ENTRY_WAIT_RETEST",
        ),
    ]
    clusters = cluster_pocket_family(rows, atr_points=15.57)
    assert len(clusters) == 2
    assert [row["signal_key"] for row in clusters[0]] == ["p1", "p2", "p3", "p4", "p5"]
    assert [row["signal_key"] for row in clusters[1]] == ["p6"]


def test_v223_splits_new_micro_wave_after_large_time_gap() -> None:
    rows = [
        _pocket(1, 4312.59, 4315.82, "2026-09-25T11:15:21+00:00"),
        _pocket(2, 4303.11, 4304.68, "2026-09-25T12:10:03+00:00"),
        _pocket(3, 4303.71, 4304.88, "2026-09-25T12:16:40+00:00"),
        _pocket(4, 4299.42, 4306.88, "2026-09-25T12:29:38+00:00"),
    ]
    clusters = cluster_pocket_family(rows, atr_points=15.57)
    assert len(clusters) == 2
    assert len(clusters[0]) == 1
    assert len(clusters[1]) == 3


def test_v223_recent_untouched_micro_wave_can_be_primary_even_if_old_wave_was_touched() -> None:
    evaluation = {
        "direction": "SHORT",
        "current_price_reference": 4306.69,
        "parent_context": {"atr_points": 15.57},
        "family": [
            _pocket(
                1,
                4306.17,
                4309.63,
                "2026-09-25T10:34:14+00:00",
                quality=70.0,
                timing="POST_MAP_TOUCH_CONFIRMED",
            ),
            _pocket(
                2,
                4312.59,
                4315.82,
                "2026-09-25T11:15:21+00:00",
                quality=45.0,
                timing="LATE_FOR_FIRST_ENTRY_WAIT_RETEST",
            ),
            _pocket(
                3,
                4303.11,
                4304.68,
                "2026-09-25T12:10:03+00:00",
                quality=48.0,
                timing="FRESH_ORIGIN_WAIT_RETEST",
            ),
            _pocket(
                4,
                4303.71,
                4304.88,
                "2026-09-25T12:16:40+00:00",
                quality=50.0,
                timing="FRESH_ORIGIN_WAIT_RETEST",
            ),
            _pocket(
                5,
                4299.42,
                4306.88,
                "2026-09-25T12:29:38+00:00",
                quality=55.0,
                timing="AT_POCKET_WAIT_CONFIRMATION",
            ),
        ],
    }
    result = select_clusters(
        evaluation,
        now=datetime(2026, 9, 25, 12, 35, tzinfo=UTC),
    )
    primary = result["primary_cluster"]
    assert primary
    assert primary["union_zone"] == {"low": 4299.42, "high": 4306.88}
    assert primary["post_map_touch_member_count"] == 0
    assert result["selection_policy"]["micro_wave_cluster_count"] >= 3

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


def test_v223_keeps_proven_retest_out_of_first_entry_primary_pool() -> None:
    evaluation = {
        "direction": "SHORT",
        "current_price_reference": 4299.9,
        "parent_context": {"atr_points": 16.0},
        "family": [
            _pocket(
                1,
                4295.41,
                4298.03,
                "2026-09-25T12:10:00+00:00",
                quality=80.0,
                timing="POST_MAP_TOUCH_CONFIRMED",
            ),
            _pocket(
                2,
                4303.11,
                4304.68,
                "2026-09-25T12:15:00+00:00",
                quality=50.0,
                timing="MOVE_STARTED_WAIT_RETEST",
            ),
        ],
    }
    result = select_clusters(
        evaluation,
        now=datetime(2026, 9, 25, 12, 20, tzinfo=UTC),
    )
    assert result["primary_cluster"]["role"] == "ACTIVE_WATCH_CLUSTER"
    assert len(result["proven_retest_clusters"]) == 1
