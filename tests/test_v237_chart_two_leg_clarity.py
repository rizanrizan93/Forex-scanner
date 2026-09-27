from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")


def test_v237_chart_accepts_explicit_next_leg_context() -> None:
    assert "next_leg_direction: str | None = None" in SOURCE
    assert "next_leg_source: dict[str, Any] | None = None" in SOURCE
    assert "next_leg_target: dict[str, Any] | None = None" in SOURCE
    assert "next_leg_terminal: dict[str, Any] | None = None" in SOURCE
    assert "next_leg_micro: dict[str, Any] | None = None" in SOURCE


def test_v237_two_leg_mode_separates_active_leg_from_reaction_leg() -> None:
    assert "two_leg_mode = bool(" in SOURCE
    assert '"LEG AKTIF {current_side}"' in SOURCE
    assert '"CEK REAKSI {next_side}"' in SOURCE
    assert '"JIKA REJECT → {next_side}"' in SOURCE
    assert '"AREA REAKSI • PANTAU {next_side}\\n"' in SOURCE


def test_v237_does_not_present_far_supply_edge_as_guaranteed_tp() -> None:
    assert "adalah batas atas zona supply HTF" in SOURCE
    assert "bukan TP yang diasumsikan akan disentuh langsung" in SOURCE
    assert "skenario bercabang, bukan jalur harga pasti" in SOURCE


def test_v237_reduces_depth_overlay_clutter() -> None:
    assert 'side != str(current_direction or "").upper()' in SOURCE
    assert "if depth_shown >= 3:" in SOURCE
    assert '"SUMBER LEG"' in SOURCE
    assert '"AREA REAKSI"' in SOURCE


def test_v237_dashboard_passes_next_leg_mapping_to_chart() -> None:
    assert "next_leg_direction=dc_next_leg_direction" in SOURCE
    assert "next_leg_source=dc_next_leg_source" in SOURCE
    assert "next_leg_target=dc_next_leg_target" in SOURCE
    assert "next_leg_terminal=dc_next_leg_terminal" in SOURCE
    assert "next_leg_micro=dc_next_micro" in SOURCE


def test_v237_warns_when_saved_map_is_stale() -> None:
    assert "Snapshot scanner ini tidak live." in SOURCE
    assert "Gunakan sebagai state terakhir yang tersimpan sampai feed pasar aktif kembali." in SOURCE
