from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")


def test_v234_chart_prefers_v229_structural_targets() -> None:
    assert "def _rizan_chart_target_ladder(" in SOURCE
    assert "structural_targets: list[dict[str, Any]] | None" in SOURCE
    structural = SOURCE.index("for raw in list(structural_targets or [])")
    fallback = SOURCE.index("if not raw_targets:", structural)
    assert structural < fallback
    assert "STRUCTURAL_M15_H1_H4" in (
        ROOT / "src/fx_scanner/demo_xau_v229_depth_execution.py"
    ).read_text(encoding="utf-8")


def test_v234_generic_fallback_path_is_preserved_when_no_two_leg_map() -> None:
    start = SOURCE.index("path_points: list[tuple[float, float, str]]")
    end = SOURCE.index('y_values = [float(visible["low"].min())', start)
    block = SOURCE[start:end]
    assert '"DEPTH / ENTRY"' in block
    assert "NEXT TARGET" in block
    assert '"NEXT LEG"' not in block
    assert 'float(target["price"])' in block


def test_v234_generic_target_labels_remain_available_as_fallback() -> None:
    assert '" • TARGET BERIKUTNYA"' in SOURCE
    assert '" • NEXT TARGET"' in SOURCE
    assert "if not two_leg_mode:" in SOURCE


def test_v234_chart_reduces_visual_clutter() -> None:
    assert "if important:" in SOURCE
    assert "depth_shown = 0" in SOURCE
    assert "if depth_shown >= 3:" in SOURCE
    assert "DEPTH / ENTRY AKTIF" in SOURCE
    assert "AREA REAKSI • PANTAU" in SOURCE


def test_v234_chart_reads_targets_from_current_v229_geometry() -> None:
    assert 'str(chart_event.get("code") or "") == "XAU_RIZAN_DEPTH_EXECUTION_V1"' in SOURCE
    assert 'chart_v229_geometry.get("children")' in SOURCE
    assert 'dict(chart_child).get("structural_targets")' in SOURCE
    assert "structural_targets=chart_structural_targets" in SOURCE
