"""Independent scalar execution audit and causal-prefix comparison."""
import sys,json
from pathlib import Path
import numpy as np
import pandas as pd

P=Path(sys.argv[1]).resolve();EXT='--extended' in sys.argv
meta=json.loads((P/'inputs/metadata.json').read_text())
bd=np.dtype([(n,t) for n,t in meta['bar_dtype']]);ed=np.dtype([(n,t) for n,t in meta['event_dtype']])
b=np.fromfile(P/'inputs/bars.bin',bd);ev=np.fromfile(P/'inputs/events.bin',ed)
hc=np.fromfile(P/'inputs/h1_close.bin','<f8')

def replay(e,g,cost,delay):
    i=int(e['entry'])+delay;s=int(e['s']);a=float(e['atr'])
    if i>=len(b) or b[i]['t']!=b[e['entry']]['t']+delay:return None
    entry=float(b[i]['o'])+(.3*cost if s==1 else 0)+s*.05*cost
    risk=max([.75,1,1.5][g//18]*a,.6*cost);stop=initial=entry-s*risk;tp=entry+s*[2,3,4][g//6%3]*a;unit=risk+.12*cost
    hold=([480,1440,2880] if EXT else [240,480,720])[g//2%3]
    cutoff=min(int(b[i]['t'])+hold,int(b[i]['t'])+1435-int(b[i]['minute']))
    if EXT:
        utcday=int(b[i]['t'])//1440;weekday=(utcday+3)%7
        cutoff=min(int(b[i]['t'])+hold,(utcday+(4-weekday+7)%7)*1440+1255)
        if cutoff<=b[i]['t']:return None
    armed=None;minr=maxr=0.;missing=0
    for k in range(i,len(b)):
        z=b[k];t=int(z['t']);op=float(z['o'])+(.3*cost if s==-1 else 0);low=float(z['l'])+(.3*cost if s==-1 else 0);high=float(z['h'])+(.3*cost if s==-1 else 0)
        if k>i:missing+=max(0,t-int(b[k-1]['t'])-1)
        carry=max(0,(t-1260)//1440-(int(b[i]['t'])-1260)//1440)*(1 if cost>=2 else .5 if cost>1 else .2) if EXT else 0
        reason=None
        if t>=cutoff:exit=op-s*.05*cost;reason=3
        else:
            if g%2 and armed is not None and t>armed and t%60==0 and np.isfinite(hc[k]):
                new=float(hc[k])-s*1.5*a;stop=max(stop,new) if s==1 else min(stop,new)
            sl=low<=stop if s==1 else high>=stop;hit=high>=tp if s==1 else low<=tp
            if sl:exit=(min(op,stop) if s==1 else max(op,stop))-s*.05*cost;reason=4 if abs(stop-initial)>1e-9 else 1
            elif hit:exit=tp-s*.05*cost;reason=2
            adverse=max(low,min(op,stop)) if s==1 else min(high,max(op,stop));favorable=min(high,tp) if s==1 else max(low,tp)
            minr=min(minr,(s*(adverse-entry)-.12*cost-carry)/unit);maxr=max(maxr,(s*(favorable-entry)-.12*cost-carry)/unit)
            if armed is None and s*(favorable-entry)>=a:armed=t
        if reason:
            r=(s*(exit-entry)-.07*cost-carry)/unit
            return dict(entry_i=i,exit_i=k,exit_t=t+(reason!=3),entry=entry,stop=initial,tp=tp,unit=unit,r=r,minr=min(minr,r),maxr=max(maxr,r),reason=reason,missing=missing)
    return None

def main():
    rows=pd.read_csv(P/'results/scalar_samples.csv');largest=0.;reasons={}
    for row in rows.itertuples():
        out=replay(ev[row.event_i],row.g,row.cost,row.delay);assert out
        for field in ['entry_i','exit_i','exit_t','entry','stop','tp','unit','r','minr','maxr','reason','missing']:
            err=abs(out[field]-getattr(row,field));largest=max(largest,err)
            assert err<1e-9,(row.event_i,field,out[field],getattr(row,field))
        reasons[str(out['reason'])]=reasons.get(str(out['reason']),0)+1
    result={'samples':len(rows),'max_absolute_error':largest,'reason_counts':reasons,'status':'PASS','extended':EXT,'scope':'Independent Python scalar vs C++ replay on archived M1, not broker-native tick execution.'}
    (P/'results/independent_audit.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

if __name__=='__main__':main()
