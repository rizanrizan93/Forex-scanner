from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v219_chart_upgrade_is_preserved_inside_rizan_style_dashboard() -> None:
    text = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    assert "Peta Harga & Supply/Demand — RIZAN-style" in text
    assert "TARGET 1" in text
    assert "NEXT SOURCE" in text
    assert '"SUMBER LEG"' in text
    assert '"AREA REAKSI"' in text
    assert "FancyArrowPatch" in text
    assert "_rizan_chart_png" in text
    assert "Download chart RIZAN-style (PNG)" in text
    assert 'file_name=f"xauusd_rizan_supply_demand_{rizan_chart_tf.lower()}.png"' in text
    assert "Timeframe chart" in text
    assert "chart_bars_m15" in text


def test_v219_chart_does_not_create_execution_authority() -> None:
    text = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    assert "Panah menunjukkan jalur preparation, bukan jaminan pergerakan harga." in text
    assert "izin order tetap mengikuti admission dan protection contract" in text
    assert "skenario bercabang, bukan jalur harga pasti" in text


def test_v2563_parent_rescue_is_explicit_but_never_execution_authority() -> None:
    text = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    assert "HTF PARENT REVERSAL RESCUE AKTIF" in text
    assert "M5 candidate/refined tetap dipertahankan sebagai SHADOW/PREPARE" in text
    assert "tidak memberi execution authority" in text


def test_v2563_chart_filters_broken_or_invalid_zones() -> None:
    text = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    assert 'zone_lifecycle.get("active") is False' in text
    assert '"BROKEN" in zone_status or "INVALID" in zone_status' in text


def test_v2563_user_facing_diagnostics_sanitize_legacy_afic_names() -> None:
    text = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    assert '.str.replace("AFIC", "RIZAN", regex=False)' in text
    assert '.replace("AFIC", "RIZAN")' in text
    assert "def _rizan_path_text" in text
    assert "def _rizan_next_action" in text
