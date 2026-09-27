from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
READER = (ROOT / "src/fx_scanner/dashboard.py").read_text(encoding="utf-8")


def test_v241_dashboard_has_profitability_truth_panel() -> None:
    assert "##### V241 — XAU Profitability Truth" in DASHBOARD
    assert "S/D prospective hold" in DASHBOARD
    assert "Primary S/D candidate" in DASHBOARD
    assert "Broker-authorized terminal sample" in DASHBOARD
    assert "Profitability validation" in DASHBOARD
    assert "Reaction ≥0,50 ATR bukan win rate" in DASHBOARD


def test_v241_dashboard_refuses_to_fabricate_pf_without_oos_row() -> None:
    assert "**Belum ada row OOS XAU di model_performance.**" in DASHBOARD
    assert "dashboard tidak boleh mengklaim win rate atau Profit Factor trading" in DASHBOARD


def test_v241_dashboard_reads_xau_outcome_ledger_read_only() -> None:
    assert "def latest_xau_outcomes" in READER
    assert 'self.client.table("xau_outcome_ledger")' in READER
    assert '"xau_outcomes": list(reader.latest_xau_outcomes())' in DASHBOARD
