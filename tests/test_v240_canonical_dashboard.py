from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")


def test_v240_dashboard_has_canonical_decision_map() -> None:
    assert "##### V240 — Canonical XAU Decision Map" in SOURCE
    assert "Satu sumber kebenaran untuk arah, Depth Candidate, entry, SL, TP" in SOURCE
    for label in (
        "Apa yang harus dilakukan sekarang",
        "Arah aktif V182",
        "Struktur aktif — bukan locator historis",
        "Demand terdekat",
        "Supply terdekat",
        "M15 confirmation",
        "M5 timing",
        "7 • Entry resmi",
        "7 • Zone watch (BUKAN ENTRY)",
        "8 • Dynamic Depth",
        "9 • Pressure / DOM",
        "10 • Execution Admission",
        "11 • SL resmi",
        "12 • TP order resmi",
        "13 • Path target (BUKAN TP order)",
        "14 • WAIT / BLOCK reason",
        "15 • Lifecycle",
        "16 • Session WIB",
    ):
        assert label in SOURCE


def test_v240_dashboard_uses_canonical_builder() -> None:
    assert "build_canonical_xau_decision" in SOURCE
    assert "v226_evaluation=v226_eval" in SOURCE
    assert "atlas_evaluation=dc_sd_eval" in SOURCE
    assert "price_now=dc_reference_price" in SOURCE


def test_v240_chart_uses_canonical_entry_and_structural_targets() -> None:
    assert "chart_structural_targets = list(v240_targets)" in SOURCE
    assert "direction=v240_direction" in SOURCE
    assert "entry_zone=v240_entry_zone" in SOURCE
    assert "structural_targets=chart_structural_targets" in SOURCE
    assert "current_direction=v240_direction" in SOURCE


def test_v240_stale_or_conflict_is_explicit_fail_closed() -> None:
    assert "**CONFLICT WAIT:**" in SOURCE
    assert "**STALE WAIT:**" in SOURCE
    assert "Jangan mengisi SL/TP dari panel lama secara manual." in SOURCE


def test_v240_reaction_metrics_are_not_mislabeled_as_trading_winrate() -> None:
    assert "Angka ini adalah reaction evidence, bukan win rate trading atau profit factor." in SOURCE



def test_v2401_dashboard_surfaces_primary_reversal_watch_without_overclaiming() -> None:
    assert "Primary Reversal Watch — area tujuan sebelum potensi reversal" in SOURCE
    assert "Area reversal utama" in SOURCE
    assert "P touch (research)" in SOURCE
    assert "P reaksi ≥0.50 ATR" in SOURCE
    assert "Touch×Reaction score" in SOURCE
    assert "bukan probabilitas terkalibrasi dan bukan izin entry" in SOURCE
    assert "Dashboard tidak mengarang probabilitas reversal." in SOURCE


def test_v249_pressure_transition_is_visible_in_canonical_dashboard():
    assert "Buyer / Seller Pressure — timing masuk zona" in SOURCE
    assert "Pressure transition" in SOURCE
    assert "Pre-touch DEMO" in SOURCE
    assert "M5-confirm DEMO" in SOURCE
    assert "evaluate_pressure_transition" in SOURCE


def test_v251_dynamic_depth_hazard_is_visible_in_canonical_dashboard():
    assert "Dynamic Depth Hazard — next depth / reversal window" in SOURCE
    assert "Next reversal band" in SOURCE
    assert "Hazard action" in SOURCE
    assert "build_dynamic_depth_hazard" in SOURCE


def test_v252_dashboard_surfaces_current_lifecycle_and_demo_execution():
    assert "Current Supply/Demand Lifecycle" in SOURCE
    assert "Riset lifecycle V226 historis" in SOURCE
    assert "current V182/V240" in SOURCE
    assert "V229 DEMO Execution — producer + child executor" in SOURCE
    assert "Execution phase" in SOURCE
    assert "Aksi child executor terbaru:" in SOURCE
    assert "Prior scope:" in SOURCE


def test_v240_mobile_operational_strip_has_price_session_gate_and_children() -> None:
    assert 'metric("Harga XAU sekarang"' in SOURCE
    assert 'metric("16 • Session WIB"' in SOURCE
    assert '"14 • WAIT / BLOCK reason"' in SOURCE
    assert "Child L1–L4 — status eksekusi DEMO" in SOURCE
    for slot in ("L1", "L2", "L3", "L4"):
        assert f'metric("{slot}"' in SOURCE


def test_v240_smartphone_sequence_matches_operational_contract() -> None:
    assert "Apa yang harus dilakukan sekarang" in SOURCE
    assert "Struktur aktif — bukan locator historis" in SOURCE
    assert "Entry → Dynamic Depth → Admission" in SOURCE
    assert "Risk & target" in SOURCE

    ordered = (
        "Apa yang harus dilakukan sekarang",
        "Struktur aktif — bukan locator historis",
        "Demand terdekat",
        "Supply terdekat",
        "M15 confirmation",
        "M5 timing",
        "Entry → Dynamic Depth → Admission",
        "8 • Dynamic Depth",
        "9 • Pressure / DOM",
        "10 • Execution Admission",
        "Risk & target",
        "11 • SL resmi",
        "12 • TP order resmi",
        "13 • Path target (BUKAN TP order)",
        "14 • WAIT / BLOCK reason",
        "15 • Lifecycle",
        "16 • Session WIB",
    )
    positions = [SOURCE.index(label) for label in ordered]
    assert positions == sorted(positions)
