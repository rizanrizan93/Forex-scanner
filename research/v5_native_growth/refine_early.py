"""Trace and refine the best V5 fixed-basket policy, not native execution."""
import sys,struct,json,math,collections,statistics,itertools,datetime
from pathlib import Path
root=Path(sys.argv[1]);raw=(root/"tape.bin").read_bytes()
n,m=struct.unpack_from("<ii",raw);assert (n,m)==(1047,2094)
bs=[struct.unpack_from("<ddii",raw,8+i*24) for i in range(n)]
ev=[struct.unpack_from("<dii",raw,8+24*n+i*16) for i in range(m)]
names=["EURUSD","XAUUSD","BTCUSD"]
def run(look,threshold,scale,limit,mask,typ=0,trace=False):
    cash=peak=100.;dd=0.;hist=[[],[],[]];sizes=[0.]*n;changed=[]
    for ts,kind,i in ev:
        pnl,ref,sym,seed=bs[i]
        if kind==0:
            h=hist[sym][-look:]
            bad=len(h)==look and (sum(x>0 for x in h)/look<threshold if typ==0 else sum(h)<0)
            reduce=not seed and cash<limit and (mask&(1<<sym)) and bad
            w=scale if reduce else 1.
            sizes[i]=cash/ref*w
            if reduce:changed.append({"i":i,"at":datetime.datetime.fromtimestamp(ts,datetime.timezone.utc).isoformat(),"symbol":names[sym],"archived_pnl":pnl,"archive_ref":ref,"sim_cash_at_entry":cash,"factor":w,"prior_wins":sum(x>0 for x in h),"prior_count":len(h)})
        else:
            cash+=sizes[i]*pnl;peak=max(peak,cash);dd=max(dd,1-cash/peak);hist[sym].append(pnl/ref)
            if cash<=0:return {"end":cash,"dd":1,"n_changed":len(changed)}
    r={"look":look,"threshold":threshold,"scale":scale,"limit":limit,"mask":mask,"type":typ,"end":cash,"dd":dd,"n_changed":len(changed)}
    if trace:r["changed"]=changed
    return r
control=run(8,.5,1,1000,7,trace=True)
assert abs(control["end"]-1662133293.0811067)<.05
top=run(8,.5,.25,1000,7,trace=True)
assert abs(top["end"]-1839014677.9631593)<.05
rows=[]
for look,threshold,scale,limit,mask,typ in itertools.product([3,4,5,6,8,10,12,16],[.4,.5,.6],[.25,.5,.75],[250,500,750,1000,1500,2000,5000],range(1,8),[0,1]):
    if typ==1 and threshold!=.5:continue
    r=run(look,threshold,scale,limit,mask,typ)
    rows.append(r)
rows.sort(key=lambda x:x["end"],reverse=True)
valid=[r for r in rows if r["dd"]<.6 and r["end"]>control["end"]]
best=valid[:10]
for i,r in enumerate(best):best[i]=run(r["look"],r["threshold"],r["scale"],r["limit"],r["mask"],r["type"],True)
report={"scope":"fixed historical basket ledger only; no native orders or floating DD; selected on same history","actual_cases":len(rows),"improved_closed_dd_under_60":len(valid),"control_end":control["end"],"control_closed_dd":control["dd"],"previous_best_exact":top,"best":best,"new_native_replays":0}
Path("early_refinement.json").write_text(json.dumps(report,indent=2))
print("V5_EARLY_REFINE",json.dumps(report))
