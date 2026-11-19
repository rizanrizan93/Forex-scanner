"""R8-L: fail-closed vendor provenance manifest for DOLLARIDXUSD M1.
Research-only. A transformed CSV hash alone is not proof of original vendor bytes.
Usage: python r8l_vendor_provenance_manifest.py manifest.json source_file
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REQUIRED = ("vendor", "instrument", "source_url", "retrieved_at_utc",
            "raw_sha256", "raw_size_bytes", "raw_file_name",
            "transform_code_sha256", "timezone_basis", "bar_timestamp_semantics")

def verify(manifest_path, raw_path):
    m=json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    missing=[k for k in REQUIRED if not m.get(k)]
    if missing:
        raise ValueError("MISSING_PROVENANCE_FIELDS:"+",".join(missing))
    if m["vendor"]!="Dukascopy" or m["instrument"].lower()!="dollaridxusd":
        raise ValueError("WRONG_VENDOR_OR_INSTRUMENT")
    if m["timezone_basis"]!="UTC" or m["bar_timestamp_semantics"]!="M1_OPEN":
        raise ValueError("UNVERIFIED_TIME_SEMANTICS")
    t=datetime.fromisoformat(m["retrieved_at_utc"].replace("Z","+00:00"))
    if t.utcoffset().total_seconds()!=0:
        raise ValueError("RETRIEVAL_TIME_NOT_UTC")
    raw=Path(raw_path).read_bytes()
    sha=hashlib.sha256(raw).hexdigest()
    if sha!=m["raw_sha256"] or len(raw)!=m["raw_size_bytes"]:
        raise ValueError("RAW_BYTES_MISMATCH")
    if Path(raw_path).name!=m["raw_file_name"]:
        raise ValueError("RAW_FILENAME_MISMATCH")
    if len(m["transform_code_sha256"])!=64:
        raise ValueError("BAD_TRANSFORM_HASH")
    return {"status":"RAW_BYTES_MATCH_MANIFEST_ONLY",
            "raw_sha256":sha,"raw_size_bytes":len(raw),
            "limitations":["Manifest claims are not independent proof of vendor authenticity",
                           "Source URL and acquisition log must be independently checked",
                           "CSV UTC/as-of/quote-age gates and real R6 replay remain separate"]}

if __name__=="__main__":
    if len(sys.argv)!=3:
        raise SystemExit("usage: r8l_vendor_provenance_manifest.py manifest.json raw_file")
    print(json.dumps(verify(sys.argv[1],sys.argv[2]),indent=2))
