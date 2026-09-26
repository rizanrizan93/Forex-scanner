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


def test_v234_path_is_now_entry_then_targets_not_next_leg() -> None:
    start = SOURCE.index("path_points: list[tuple[float, float, str]]")
    end = SOURCE.index('y_values = [float(visible["low"].min())', start)
    block = SOURCE[start:end]
    assert '"DEPTH / ENTRY"' in block
    assert "NEXT TARGET" in block
    assert '"NEXT LEG"' not in block
    assert 'float(target["price"])' in block


def test_v234_last_arrow_is_explicitly_next_target() -> None:
    assert '" • TARGET BERIKUTNYA"' in SOURCE
    assert '" • NEXT TARGET"' in SOURCE
    assert "Panah terakhir selalu berakhir pada target berikutnya/terminal" in SOURCE


def test_v234_chart_reduces_visual_clutter() -> None:
    assert "if important:" in SOURCE
    assert "for depth in list(depth_overlays or [])[:4]:" in SOURCE
    assert "DEPTH / ENTRY AKTIF" in SOURCE
    assert "Target berikutnya" in SOURCE
    assert "Target terminal chart" in SOURCE


def test_v234_chart_reads_targets_from_current_v229_geometry() -> None:
    assert 'str(chart_event.get("code") or "") == "XAU_RIZAN_DEPTH_EXECUTION_V1"' in SOURCE
    assert 'chart_v229_geometry.get("children")' in SOURCE
    assert 'dict(chart_child).get("structural_targets")' in SOURCE
    assert "structural_targets=chart_structural_targets" in SOURCE
