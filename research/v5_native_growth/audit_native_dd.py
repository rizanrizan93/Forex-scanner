"""Read actual completed native receipts from immutable R15 archives; no counterfactual estimates."""
import hashlib,json,zipfile,gzip,io,sys
from pathlib import Path
root=Path(sys.argv[1])
sha=lambda b:hashlib.sha256(b).hexdigest()
out=[]
for manifest in ["native_control_manifest.json","native_pds_manifest.json"]:
    m=json.loads((root/manifest).read_text())
    parts=[]
    for p in m["parts"]:
        b=(root/p["name"]).read_bytes()
        assert len(b)==p["bytes"] and sha(b)==p["sha256"],p["name"]
        parts.append(b)
    raw=b"".join(parts)
    assert len(raw)==m.get("archive_bytes",m.get("bytes")) and sha(raw)==m.get("archive_sha256",m.get("sha256"))
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for name in z.namelist():
            if not name.endswith(".json.gz"):continue
            d=json.loads(gzip.decompress(z.read(name)))
            s=d.get("Summary")
            if not s or "EndingBalance" not in s:continue
            a=d.get("Annual",[])
            if len(a)<8 or a[0].get("Year")!=2019 or a[-1].get("Year")!=2026:continue
            assert s["TotalContributions"]==100
            l=d["Ledger"];assert len(l)==s["Baskets"]
            assert abs(100+sum(x["Pnl"] for x in l)-s["EndingBalance"])<.05
            out.append({"manifest":manifest,"archive":m.get("archive_name",m.get("filename")),"sha256":sha(raw),"file":name,"case":s["cfg"]["Name"],"balance":s["EndingBalance"],"floating_dd_pct":s["MaxEquityDDPct"],"closed_dd_pct":s["MaxClosedDDPct"],"baskets":s["Baskets"],"orders":s["Orders"],"peak_open_risk_pct":s["MaxObservedOpenRiskPct"],"peak_margin_pct":s["MaxObservedMarginPct"],"cutoff":s["ActualCutoff"],"errors":s["ErrorCount"],"open_positions":s["OpenPositions"],"quarantined":s["Quarantined"],"addon_audit":d.get("SparseAudit",d.get("AddonAudit"))})
assert any(abs(r["balance"]-1662133293.0811067)<.01 for r in out)
assert any(r["manifest"]=="native_pds_manifest.json" for r in out)
r={"scope":"existing native synthetic market replay receipts, not newly executed replays","completed_continuous_receipts":out,"new_native_replays":0}
Path("native_dd_audit.json").write_text(json.dumps(r,indent=2))
print("NATIVE_DD_AUDIT",json.dumps(r))
