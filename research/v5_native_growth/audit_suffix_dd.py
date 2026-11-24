"""Audit the floating-DD suffix of the locked fixed-basket sensitivity.
This is a conditional proportional-path diagnostic, NOT a new price replay.
"""
import hashlib,json,zipfile,gzip,io,sys,datetime,math
from pathlib import Path
root=Path(sys.argv[1]);m=json.loads((root/"native_control_manifest.json").read_text())
h=lambda b:hashlib.sha256(b).hexdigest()
parts=[]
for p in m["parts"]:
    b=(root/p["name"]).read_bytes()
    assert len(b)==p["bytes"] and h(b)==p["sha256"]
    parts.append(b)
raw=b"".join(parts)
assert h(raw)==m["archive_sha256"]
with zipfile.ZipFile(io.BytesIO(raw)) as z:
    found=[]
    for name in z.namelist():
        if name.endswith(".json.gz"):
            d=json.loads(gzip.decompress(z.read(name)))
            if abs(d.get("Summary",{}).get("EndingBalance",0)-1662133293.0811067)<.01 and d["Summary"]["Baskets"]==1047:found.append(d)
assert len(found)==1
d=found[0];s=d["Summary"];bs=d["Ledger"]
def dt(v):return datetime.datetime.fromisoformat(v.replace("Z","+00:00")).replace(tzinfo=datetime.timezone.utc)
events=[]
for i,t in enumerate(bs):
    events.extend([(dt(t["Entry"]),0,i),(dt(t["Exit"]),1,i)])
events.sort()
cash=100.;ref=[0.]*len(bs)
for _,kind,i in events:
    if kind==0:ref[i]=cash
    else:cash+=bs[i]["Pnl"]
assert abs(cash-s["EndingBalance"])<.02
base_cash=cash
cash=100.;hist=[];sizes=[0.]*len(bs);changed=[]
for ts,kind,i in events:
    t=bs[i]
    if kind==0:
        w=1.
        if t["Symbol"]=="XAUUSD" and t.get("Origin")!="SEED" and cash<1500 and len(hist)>=8 and sum(x>0 for x in hist[-8:])/8<.6:
            w=.25;changed.append(i)
        sizes[i]=cash/ref[i]*w
    else:
        cash+=sizes[i]*t["Pnl"]
        if t["Symbol"]=="XAUUSD":hist.append(t["Pnl"])
assert abs(cash-2091130955.0952506)<.05 and len(changed)==24
ratio=cash/base_cash
# The late path is proportional only when EVERY later and still-open
# archived basket has the same size multiplier. Determine a conservative
# cutoff after all non-proportional basket exits.
different=[i for i,k in enumerate(sizes) if abs(k-ratio)>1e-8*max(1.,ratio)]
cut=max(dt(bs[i]["Exit"]) for i in different)
assert cut>=max(dt(bs[i]["Exit"]) for i in changed)
curve=sorted(d["EquityCurve"],key=lambda q:dt(q["At"]))
late=[q for q in curve if dt(q["At"])>cut]
early=[q for q in curve if dt(q["At"])<=cut]
assert late and early
peak=0.;maxdd=0.;peak_at=None;dd_at=None
for q in late:
    x=q["Equity"]
    if x>peak:peak=x;peak_at=q["At"]
    dd=1-x/peak
    if dd>maxdd:maxdd=dd;dd_at=q["At"]
# Cumulative DD in original native curve includes intra-hour observations;
# the following checks whether the original maximum developed later.
before_native_dd=max(q["DD"] for q in early)
after_native_dd=max(q["DD"] for q in late)
assert abs(after_native_dd-s["MaxEquityDDPct"])<.000001
r={"scope":"conditional fixed-path suffix only; no changed fills, costs, min lots, margin, or order admission recomputed; prefix floating DD and native challenger DD remain unknown","control_balance":base_cash,"control_floating_dd_pct":s["MaxEquityDDPct"],"locked_balance":cash,"proportional_multiplier":ratio,"last_nonproportional_basket_exit":cut.isoformat(),"modified_baskets":len(changed),"nonproportional_baskets":len(different),"late_hourly_marks":len(late),"early_hourly_marks":len(early),"late_path_hourly_floating_dd_pct":100*maxdd,"late_dd_trough_at":dd_at,"original_cumulative_floating_dd_before_cut_pct":before_native_dd,"original_cumulative_floating_dd_after_cut_pct":after_native_dd,"candidate_full_floating_dd_pct":None,"new_native_replays":0}
Path("suffix_dd.json").write_text(json.dumps(r,indent=2))
print("SUFFIX_DD_AUDIT",json.dumps(r))
