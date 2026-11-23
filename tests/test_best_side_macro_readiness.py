"""Best-side macro receipt rejects promoting retrospective winners to live signals."""
from datetime import UTC,datetime
from pathlib import Path
import importlib.util
import pytest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts/best_side_macro_readiness.py"

def load():
    spec=importlib.util.spec_from_file_location("best_side_macro_readiness",SCRIPT)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_absent_archives_fail_closed(monkeypatch,tmp_path):
    module=load()
    monkeypatch.setattr(module,"REF",tmp_path)
    monkeypatch.setattr(module,"R18",tmp_path/"absent.json")
    with pytest.raises(FileNotFoundError,match="MISSING_ARCHIVED_EVIDENCE"):
        module.audited(datetime(2026,11,23,tzinfo=UTC))

def test_readiness_requires_full_archived_proof_and_never_issues_live_direction():
    module=load()
    if not module.R18.is_file():
        pytest.skip("Archive checkout not present in this test context")
    out=module.audited(datetime(2026,11,23,13,tzinfo=UTC))
    assert out["research_only"] is True and out["execution_authority"] is False
    assert set(out["rows"])=={"D1_R18_SELL","W1_R27_BUY","W1_R24_SELL"}
    assert all(row["direction"]=="WAIT" and row["state"]=="NOT_READY"
               and row["execution_authority"] is False and row["blockers"]
               for row in out["rows"].values())
    assert "2026-04-26" in out["news_source_last_available"]
    assert out["rows"]["D1_R18_SELL"]["historical_config_present"] is True
    assert out["rows"]["W1_R27_BUY"]["historical_config_present"] is True
