"""Compare archived native control/PDS execution, not hypothetical market replay."""
import collections,datetime,gzip,hashlib,io,json,statistics,sys,zipfile
from pathlib import Path
root=Path(sys.argv[1])
sha=lambda b:hashlib.sha256(b).hexdigest()
def load(name,target):
    m=json.loads((root/name).read_text())
    parts=[]
    for p in m["parts"]:
        b=(root/p["name"]).read_bytes()
        assert len(b)==p["bytes"] and sha(b)==p["sha256"]
        parts.append(b)
    raw=b"".join(parts)
    assert sha(raw)==m.get("archive_sha256",m.get("sha256"))
    found=[]
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for f in z.namelist():
            if f.endswith(".json.gz"):
                d=json.loads(gzip.decompress(z.read(f)))
                if abs(d.get("Summary",{}).get("EndingBalance",0)-target)<.01:found.append(d)
    assert len(found)==1
    return found[0]
c=load("native_control_manifest.json",1662133293.0811067)
p=load("native_pds_manifest.json",1671468104.9086576)
def key(t):return (t["Symbol"],t["Entry"],t.get("Origin",""))
def summary(d):
    s=d["Summary"]
    return {k:s[k] for k in ("EndingBalance","MaxEquityDDPct","MaxClosedDDPct","Baskets","Orders","TotalContributions","ActualCutoff","MaxObservedOpenRiskPct","MaxObservedMarginPct","ErrorCount")}
cc={key(t):t for t in c["Ledger"]};pp={key(t):t for t in p["Ledger"]}
assert len(cc)==len(c["Ledger"]) and len(pp)==len(p["Ledger"])
missing=sorted(cc.keys()-pp.keys());extra=sorted(pp.keys()-cc.keys());common=cc.keys()&pp.keys()
def stat(ts):
    ts=list(ts);a=sum(t["Pnl"] for t in ts if t["Pnl"]>0);b=-sum(t["Pnl"] for t in ts if t["Pnl"]<0)
    return {"count":len(ts),"wins":sum(t["Pnl"]>0 for t in ts),"pnl":a-b,"pf":a/b if b else None}
inc=collections.defaultdict(float)
for k in common:inc[k[0]]+=pp[k]["Pnl"]-cc[k]["Pnl"]
delta=sum(inc.values())+sum(pp[k]["Pnl"] for k in extra)-sum(cc[k]["Pnl"] for k in missing)
assert abs(delta-(p["Summary"]["EndingBalance"]-c["Summary"]["EndingBalance"]))<.05
# Quantify child/order capacity rather than guessing from basket count.
orders=collections.defaultdict(list)
for o in c["OrderLedger"]:
    bits=o["Label"].split("|")
    if len(bits)>=2:orders[(o["SymbolName"],bits[1])].append(o)
caps={}
for sym in ["EURUSD","XAUUSD","BTCUSD"]:
    groups=[g for (s,k),g in orders.items() if s==sym and not g[0]["Label"].startswith("RZSEED|")]
    v=[]
    for side in ["Buy","Sell"]:
        a=[g for g in groups if g[0]["Side"]==side]
        if not a:continue
        pnls=[sum(o["NetProfit"] for o in g) for g in a]
        max_orders=max(map(len,a))
        cap=[g for g in a if len(g)>=32] if sym=="BTCUSD" else []
        v.append({"side":side,"groups":len(a),"wins":sum(q>0 for q in pnls),"net":sum(pnls),"max_orders_in_group":max_orders,"median_orders":statistics.median(map(len,a)),"cap_32_groups":len(cap) if sym=="BTCUSD" else None,"cap_32_net":sum(o["NetProfit"] for g in cap for o in g) if sym=="BTCUSD" else None})
    caps[sym]=v
out={"scope":"verified archived native executions; no new market replay","control":summary(c),"pds":summary(p),"common_entry_keys":len(common),"missing_original_keys":[list(k) for k in missing],"extra_keys":len(extra),"extra_stats":stat(pp[k] for k in extra),"common_pnl_change_by_symbol":dict(inc),"total_delta":delta,"baseline_order_groups":caps,"new_native_replays":0}
Path("pds_interference.json").write_text(json.dumps(out,indent=2))
print("PDS_INTERFERENCE",json.dumps(out))
