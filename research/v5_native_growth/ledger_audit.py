"""Audit actual archived native basket/order ledgers, not hypothetical replay."""
import hashlib,json,zipfile,gzip,sys,collections,statistics,io
from pathlib import Path
root=Path(sys.argv[1]);m=json.loads((root/"native_control_manifest.json").read_text())
h=lambda b:hashlib.sha256(b).hexdigest()
raw=[]
for p in m["parts"]:
    b=(root/p["name"]).read_bytes()
    assert len(b)==p["bytes"] and h(b)==p["sha256"],p["name"]
    raw.append(b)
z=b"".join(raw);assert len(z)==m["archive_bytes"] and h(z)==m["archive_sha256"]
with zipfile.ZipFile(io.BytesIO(z)) as f:
    print("ARCHIVE_FILES",[(i.filename,i.file_size) for i in f.infolist()])
    matches=[]
    for name in f.namelist():
        if not name.endswith(".json.gz"):continue
        with gzip.GzipFile(fileobj=io.BytesIO(f.read(name))) as stream:d=json.load(stream)
        if abs(d.get("Summary",{}).get("EndingBalance",0)-1662133293.0811067)<.01 and d["Summary"]["Baskets"]==1047:matches.append(d)
    assert len(matches)==1,"expected one original continuous case"
d=matches[0];s=d["Summary"];assert abs(s["MaxEquityDDPct"]-56.67209330213908)<1e-6
l=d["Ledger"];orders=d["OrderLedger"]
assert len(l)==1047
groups=collections.defaultdict(list);byentry=collections.defaultdict(list)
for t in l:groups[t["Symbol"]].append(t)
for o in orders:
    a=o["Label"].split("|")
    if len(a)>=2:byentry[(o["SymbolName"],a[1])].append(o)
def stat(ts):
    pos=sum(max(0,t["Pnl"]) for t in ts);neg=sum(max(0,-t["Pnl"]) for t in ts)
    ref=[t["Pnl"]/t["ReferenceBalance"] for t in ts if t.get("ReferenceBalance",0)>0]
    return dict(baskets=len(ts),wins=sum(t["Pnl"]>0 for t in ts),net_pnl=sum(t["Pnl"] for t in ts),pf=pos/neg if neg else None,median_relative_pnl=statistics.median(ref) if ref else None,relative_sample_count=len(ref),children=sum(t["AcceptedChildren"] for t in ts),max_children=max(t["AcceptedChildren"] for t in ts))
btcgroups=[v for (sym,k),v in byentry.items() if sym=="BTCUSD" and not v[0]["Label"].startswith("RZSEED|")]
btc_cap=[v for v in btcgroups if len(v)>=32]
cap_sides=collections.Counter(v[0]["Side"] for v in btc_cap)
r={"archive_sha256":h(z),"baseline":{"balance":s["EndingBalance"],"floating_dd":s["MaxEquityDDPct"],"baskets":s["Baskets"],"orders":s["Orders"],"observed_margin":s["MaxObservedMarginPct"],"observed_open_risk":s["MaxObservedOpenRiskPct"]},"per_symbol":{k:stat(v) for k,v in groups.items()},"seed_audit":d.get("SeedAudit"),"btc_order_groups":len(btcgroups),"btc_order_groups_ge32":len(btc_cap),"btc_cap_sides":dict(cap_sides),"btc_cap_group_pnl":sum(o["NetProfit"] for v in btc_cap for o in v),"btc_cap_group_winners":sum(sum(o["NetProfit"] for o in v)>0 for v in btc_cap),"native_replays_new":0,"note":"Archived ledger descriptive audit only. Child fills grouped by label second segment; group count is not a counterfactual. Dollar PnL depends on chronological balance and cannot be added to infer new ending cash."}
Path("ledger_audit.json").write_text(json.dumps(r,indent=2))
print("NATIVE_LEDGER_AUDIT",json.dumps(r))
