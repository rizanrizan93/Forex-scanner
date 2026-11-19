"""ZIP audit is a provenance check, never a predictive performance test."""
from io import BytesIO
import zipfile
import pytest
from scripts.audit_frbsf_usmpd_surprises_r1 import audit

def test_audit_labels_ex_post_data_not_trading_accuracy():
    out=BytesIO()
    with zipfile.ZipFile(out,"w") as z:
        z.writestr("USMPD-policy-surprises.csv","date,MP1,MP2\n2025-01-01,0.02,0.03\n")
    r=audit(out.getvalue())
    assert len(r["zip_sha256"])==64
    assert r["xau_h1_h4_accuracy_tested"] is False
    assert r["only_causal_after_window_closes"] is True
    assert r["files"][0]["first_line_header_or_text"]=="date,MP1,MP2"

def test_reject_invalid_zip():
    with pytest.raises(ValueError,match="NOT_BOUNDED_ZIP"):
        audit(b"not a ZIP")
