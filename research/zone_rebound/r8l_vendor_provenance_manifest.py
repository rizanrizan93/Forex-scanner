"""R8-L: fail-closed vendor provenance manifest for DOLLARIDXUSD M1.
Research-only. Matching a manifest is not independent vendor authentication.
"""
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

REQUIRED = ("vendor", "instrument", "source_url", "retrieved_at_utc",
            "raw_sha256", "raw_size_bytes", "raw_file_name",
            "transform_code_sha256", "timezone_basis", "bar_timestamp_semantics")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")

def verify(manifest_path, raw_path):
    m = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if not isinstance(m, dict):
        raise ValueError("INVALID_MANIFEST_OBJECT")
    missing = [k for k in REQUIRED if k not in m or m[k] is None or m[k] == ""]
    if missing:
        raise ValueError("MISSING_PROVENANCE_FIELDS:" + ",".join(missing))
    if m["vendor"] != "Dukascopy" or not isinstance(m["instrument"], str) or m["instrument"].lower() != "dollaridxusd":
        raise ValueError("WRONG_VENDOR_OR_INSTRUMENT")
    if m["timezone_basis"] != "UTC" or m["bar_timestamp_semantics"] != "M1_OPEN":
        raise ValueError("UNVERIFIED_TIME_SEMANTICS")
    if not isinstance(m["retrieved_at_utc"], str) or not m["retrieved_at_utc"].endswith("Z"):
        raise ValueError("RETRIEVAL_TIME_NOT_UTC")
    try:
        t = datetime.fromisoformat(m["retrieved_at_utc"][:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("BAD_RETRIEVAL_TIME") from exc
    if t > datetime.now(timezone.utc):
        raise ValueError("RETRIEVAL_TIME_IN_FUTURE")
    if not isinstance(m["transform_code_sha256"], str) or not SHA256.fullmatch(m["transform_code_sha256"]):
        raise ValueError("BAD_TRANSFORM_HASH")
    if not isinstance(m["raw_sha256"], str) or not SHA256.fullmatch(m["raw_sha256"]):
        raise ValueError("BAD_RAW_HASH")
    if type(m["raw_size_bytes"]) is not int or m["raw_size_bytes"] <= 0:
        raise ValueError("BAD_RAW_SIZE")
    if not isinstance(m["source_url"], str) or urlparse(m["source_url"]).scheme != "https":
        raise ValueError("BAD_SOURCE_URL")
    if not isinstance(m["raw_file_name"], str) or Path(m["raw_file_name"]).name != m["raw_file_name"]:
        raise ValueError("BAD_RAW_FILENAME")
    raw = Path(raw_path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if sha != m["raw_sha256"] or len(raw) != m["raw_size_bytes"]:
        raise ValueError("RAW_BYTES_MISMATCH")
    if Path(raw_path).name != m["raw_file_name"]:
        raise ValueError("RAW_FILENAME_MISMATCH")
    return {"status": "RAW_BYTES_MATCH_MANIFEST_ONLY", "raw_sha256": sha,
            "raw_size_bytes": len(raw), "limitations": [
                "Manifest claims are not independent proof of vendor authenticity",
                "Source URL and acquisition log must be independently checked",
                "CSV UTC/as-of/quote-age gates and real R6 replay remain separate"]}

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: r8l_vendor_provenance_manifest.py manifest.json raw_file")
    print(json.dumps(verify(sys.argv[1], sys.argv[2]), indent=2))
