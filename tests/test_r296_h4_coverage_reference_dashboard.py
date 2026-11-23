"""Frozen R29.1 59.94% high-coverage archival benchmark is NEVER a live BUY."""
import json
from pathlib import Path
import pytest

from fx_scanner import r296_h4_coverage_reference_dashboard as view


def test_exact_historical_sha_policies_and_2026_frequency_failure():
    lock,diag=view.load_verified()
    assert lock["historical_pooled"]["n"]==332
    assert lock["historical_pooled"]["correct"]==199
    assert abs(lock["historical_pooled"]["accuracy"]-199/332)<1e-10
    assert (lock["annual_policies"]["2025"]["evaluation"]["n"],
            lock["annual_policies"]["2025"]["evaluation"]["correct"])==(176,108)
    assert (lock["annual_policies"]["2026"]["evaluation"]["n"],
            lock["annual_policies"]["2026"]["evaluation"]["correct"])==(13,8)
    carry=diag["carry_2025_to_2026"]
    assert (carry["n"],carry["correct"])==(111,54)
    assert carry["net_mean_after_assumed_cost_usd_oz"]<0
    assert diag["decision"]=="LOCK_AS_HISTORICAL_FREQUENCY_REFERENCE_NOT_SIGNAL_PROMOTION"
    assert diag["execution_authority"] is False


def test_modified_source_sha_refused(monkeypatch,tmp_path):
    p=tmp_path/"tampered.json"
    lock=json.loads(view.LOCK.read_text())
    lock["source_json_sha256"]="bad"
    p.write_text(json.dumps(lock))
    monkeypatch.setattr(view,"LOCK",p)
    with pytest.raises(ValueError,match="NOT_VERIFIED"):
        view.load_verified()


def test_static_archival_panel_does_not_emit_buy_direction():
    class Spy:
        def __init__(self):self.metrics=[];self.warnings=[];self.tables=[];self.captions=[]
        def markdown(self,x):pass
        def container(self,border=False):return self
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def columns(self,n):return [self]*n
        def metric(self,label,value):self.metrics.append((label,value))
        def caption(self,x):self.captions.append(x)
        def dataframe(self,x,**kw):self.tables.append(x)
        def warning(self,x):self.warnings.append(x)
    st=Spy()
    view.render_h4_high_coverage_reference(st)
    assert [m[1] for m in st.metrics]==["332","126"]
    assert len(st.tables)==1 and len(st.tables[0])==3
    assert any("TIDAK DIPROMOSIKAN" in x for x in st.warnings)
    assert any("48,65%" in x for x in st.warnings)
    source=(Path(__file__).resolve().parents[1]/
            "src/fx_scanner/r296_h4_coverage_reference_dashboard.py").read_text()
    assert "render_h4_high_coverage_reference" in source
    assert "fetch(" not in source
    assert "place_order(" not in source
    assert "execute_market_order(" not in source
