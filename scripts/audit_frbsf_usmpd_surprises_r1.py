"""Audit official SF Fed USMPD public ZIP: provenance and schema ONLY.

No trading-signal inference. Files are inspected in memory, never executed.
Network source is the exact, fixed official SF Fed archive URL. The ZIP may
contain ex-post monetary policy surprises whose measurement windows only
finish AFTER FOMC communication. They cannot be used before publication.
"""
from __future__ import annotations
import hashlib, io, json, urllib.request, zipfile
from pathlib import Path

URL="https://www.frbsf.org/wp-content/uploads/monetary-policy-surprises.zip"

def audit(raw:bytes, *, url=URL):
    if len(raw)>20_000_000 or len(raw)<16 or raw[:2]!=b"PK":
        raise ValueError("NOT_BOUNDED_ZIP")
    z=zipfile.ZipFile(io.BytesIO(raw))
    contents=[]
    for item in z.infolist():
        if item.is_dir():continue
        if item.file_size>15_000_000:
            raise ValueError("UNBOUNDED_UNCOMPRESSED_FILE")
        first_line=None
        if item.filename.lower().endswith((".csv",".txt",".r",".tsv")):
            preview=z.open(item).read(1024).decode("utf-8-sig","replace")
            first_line=preview.splitlines()[0][:300] if preview.splitlines() else None
        contents.append({"filename":item.filename,
                         "uncompressed_bytes":item.file_size,
                         "first_line_header_or_text":first_line})
    return {
        "contract":"FRBSF_USMPD_PUBLIC_ZIP_SOURCE_AUDIT_V1",
        "source_url":url,"zip_sha256":hashlib.sha256(raw).hexdigest(),
        "zip_bytes":len(raw),"files":contents,
        "source_type":"FOMC_EVENT_STUDY_EX_POST_NOT_LIVE_PRICE_FEED",
        "xau_h1_h4_accuracy_tested":False,
        "only_causal_after_window_closes":True,
    }

def main():
    request=urllib.request.Request(URL,headers={"User-Agent":"RIZAN-Research/1.0 (source audit)"})
    with urllib.request.urlopen(request,timeout=25) as response:
        raw=response.read(20_000_001)
    result=audit(raw)
    destination=Path("artifacts/frbsf-usmpd-source-audit.json")
    destination.parent.mkdir(exist_ok=True,parents=True)
    destination.write_text(json.dumps(result,indent=2)+"\n")
    print("FRBSF_USMPD_SOURCE_AUDIT",json.dumps(result))
if __name__=="__main__":main()
