"""Prepare archived basket events for fixed-fill allocation sensitivity only."""
import hashlib,json,zipfile,gzip,io,sys,datetime,struct,collections
from pathlib import Path
root=Path(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
m=json.loads((root/"native_control_manifest.json").read_text())
h=lambda b:hashlib.sha256(b).hexdigest()
parts=[]
for p in m["parts"]:
    b=(root/p["name"]).read_bytes()
    assert len(b)==p["bytes"] and h(b)==p["sha256"]
    parts.append(b)
raw=b"".join(parts);assert h(raw)==m["archive_sha256"]
with zipfile.ZipFile(io.BytesIO(raw)) as z:
    candidates=[]
    for n in z.namelist():
        if n.endswith(".json.gz"):
            d=json.loads(gzip.decompress(z.read(n)))
            if abs(d.get("Summary",{}).get("EndingBalance",0)-1662133293.0811067)<.01 and d["Summary"]["Baskets"]==1047:candidates.append(d)
assert len(candidates)==1
d=candidates[0]
assert d["Summary"]["TotalContributions"]==100
ledger=d["Ledger"];assert len(ledger)==1047
def at(s):
    q=datetime.datetime.fromisoformat(s.replace("Z","+00:00"))
    return q.replace(tzinfo=datetime.timezone.utc).timestamp()
# Entry and exit times from the basket record; strictly earlier settlement
# information only. Same-timestamp entries before exits (conservative).
events=[]
for i,t in enumerate(ledger):
    start,end=at(t["Entry"]),at(t["Exit"])
    assert start<=end
    events.append((start,0,i));events.append((end,1,i))
events.sort()
cash=100.;refs=[0.]*len(ledger)
for _,kind,i in events:
    if kind==0:refs[i]=cash
    else:cash+=ledger[i]["Pnl"]
assert abs(cash-d["Summary"]["EndingBalance"])<.02
assert min(refs)>0
symbols={"EURUSD":0,"XAUUSD":1,"BTCUSD":2}
with (out/"tape.bin").open("wb") as f:
    f.write(struct.pack("<ii",len(ledger),len(events)))
    for i,t in enumerate(ledger):
        f.write(struct.pack("<ddii",float(t["Pnl"]),refs[i],symbols[t["Symbol"]],int(t.get("Origin")=="SEED")))
    for ts,kind,i in events:f.write(struct.pack("<dii",ts,kind,i))
(out/"source.json").write_text(json.dumps({"archive_sha256":h(raw),"native_summary":d["Summary"],"baskets":len(ledger),"events":len(events),"baseline_reconstructed_cash":cash,"actual_market_replay":False,"floating_dd_available_for_counterfactual":False},indent=2))
print("ARCHIVE_FIXED_PATH",len(ledger),cash,flush=True)
