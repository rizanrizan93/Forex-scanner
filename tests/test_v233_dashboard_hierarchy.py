from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")


def test_v233_operational_hierarchy_is_explicit_and_ordered() -> None:
    summary = SOURCE.index("1 • RINGKASAN KEPUTUSAN")
    zone = SOURCE.index("### 2 • Zona Utama & Depth Entry")
    execution = SOURCE.index("### 3 • Eksekusi Sekarang")
    position = SOURCE.index("### 4 • Manajemen Posisi XAUUSD")

    assert summary < zone < execution < position
    assert "Urutan baca utama:" in SOURCE
    assert "Ringkasan keputusan → 2 Zona & Depth → 3 Eksekusi sekarang" in SOURCE


def test_v233_secondary_panels_are_collapsed_by_default() -> None:
    expected = (
        "Detail setup multi-timeframe — H1 / M5 / M15 / DOM / Event",
        "Riset & evidence prospective — V197 sampai V201",
        "Riset HTF, atlas Supply/Demand & validasi zona",
        "Detail execution, admission & diagnostik",
        "Forecast ensemble & probabilitas tambahan",
        "Detail order blueprint & broker timeline",
        "Expected move & riwayat forecast",
    )
    for label in expected:
        marker = f'with st.expander("{label}", expanded=False):'
        assert marker in SOURCE


def test_v233_dashboard_recognizes_dedicated_v229_child_lane() -> None:
    assert '"XAU_RIZAN_DEPTH_EXECUTION_V1"' in SOURCE
    assert '"DEDICATED CHILD ELIGIBLE"' in SOURCE
    assert "4-CHILD 2+2" in SOURCE
    assert "Tidak diteruskan ke generic MARKET handoff." in SOURCE


def test_v233_keeps_mobile_first_css() -> None:
    assert "@media (max-width: 768px)" in SOURCE
    assert ".rizan-flow-note" in SOURCE
