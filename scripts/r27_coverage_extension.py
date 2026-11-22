"""R27 coverage extension for separate direction specialists.
Train -> candidate selection year -> independent extension selection year -> test.
Fixed accuracy floors; abstain when no candidate qualifies. No change to archived
RIZAN benchmarks. Historical research only, never production/orders/zones.
"""
import argparse,itertools,json,hashlib
from pathlib import Path
import numpy as np,pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from r14_multitimeframe_direction import load_tf
from r25_eight_specialists import setup,macro_sources
from r18_asymmetric_direction import side_metrics
from r15_direction_tournament import score
O=Path("artifacts");O.mkdir(exist_ok=True)
def m(y,s,side):return side_metrics(y,s,side)
def choose(pool,y,side,floor,minn):
    # pool selected using ONLY earlier validation. This is a separate policy
    # selection window. Baseline is first qualifying candidate by earlier rank.
    elig=[]
    for p in pool:
        r=m(y,p["v"],side)
        if r["n"]>=minn and r["accuracy"]>=floor:
            elig.append(p)
    zero=np.zeros(len(y),bool)
    if not elig:return None,[],zero
    head=elig[0];union=head["v"].copy();add=[]
    for _ in range(3):
        best=None
        for p in pool:
            if p is head or any(p is q for q in add):continue
            marginal=p["v"]&~union
            r=m(y,marginal,side);total=m(y,union|p["v"],side)
            if r["n"]<max(3,minn//3) or r["accuracy"]<floor or total["accuracy"]<floor:continue
            rank=(r["n"],total["lower95"],r["lower95"])
            if best is None or rank>best[0]:best=(rank,p)
        if best is None:break
        add.append(best[1]);union|=best[1]["v"]
    return head,add,union
def run(tf,sources):
    d,z,_,y,valid,times=load_tf(tf)
    groups,gates,extra=setup(tf,d,z,times,sources)
    valid &= extra
    mat={}
    for k,f in groups.items():
        a=f.to_numpy(float);mat[k]=a;valid &= np.isfinite(a).all(axis=1)
    gates={k:np.asarray(v,bool) for k,v in gates.items()}
    mature=pd.Series(times,index=d.index).shift(-1)
    minsel={"1h":50,"4h":25,"1D":18,"1W":8}[tf]
    mintrain={"1h":500,"4h":250,"1D":120,"1W":55}[tf]
    floors=[.60,.70,.80]
    totals={str(f):{k:[] for k in ("single","extended")} for f in floors}
    annual=[];fits=rules=0
    for yr in (range(2023,2027) if tf in ("1h","4h") else range(2019,2027)):
        t=pd.Timestamp(f"{yr}-01-01",tz="UTC");b=t-pd.DateOffset(years=1);a=b-pd.DateOffset(years=1);end=t+pd.DateOffset(years=1)
        sel=valid&(times>=a)&(times<b)&(mature<b).to_numpy()
        val=valid&(times>=b)&(times<t)&(mature<t).to_numpy()
        te=valid&(times>=t)&(times<end)&(mature<end).to_numpy()
        if min(sel.sum(),val.sum(),te.sum())<2*minsel:continue
        pools=[[],[]]
        for group,x in mat.items():
            for years,C in itertools.product([2,4,8],[.025,.3]):
                tr=valid&(times>=a-pd.DateOffset(years=years))&(mature<a).to_numpy()
                if tr.sum()<mintrain or len(np.unique(y[tr]))<2:continue
                for side in (0,1):
                    model=make_pipeline(StandardScaler(),LogisticRegression(C=C,max_iter=500))
                    model.fit(x[tr],(y[tr]==side).astype(int));fits+=1
                    ps=model.predict_proba(x[sel])[:,1];pv=model.predict_proba(x[val])[:,1];pt=model.predict_proba(x[te])[:,1]
                    for cut in [.50,.52,.55,.58,.60,.65,.70,.75,.80]:
                        for gn,G in gates.items():
                            rules+=1
                            s=(ps>=cut)&G[sel];r=m(y[sel],s,side)
                            if r["n"]<max(minsel,int(.015*sel.sum())):continue
                            pools[side].append({"rank":(r["lower95"],r["n"]),"s":s,"v":(pv>=cut)&G[val],"t":(pt>=cut)&G[te],
                                "config":{"group":group,"years":years,"C":C,"cut":cut,"gate":gn,"selection":r}})
        # Deduplicate candidates using selection-year signal traces ONLY.
        for side in (0,1):
            uniq=[];seen=set()
            for p in sorted(pools[side],key=lambda x:x["rank"],reverse=True):
                sig=hashlib.sha256(np.packbits(p["s"]).tobytes()).digest()
                if sig in seen:continue
                seen.add(sig);uniq.append(p)
                if len(uniq)>=40:break
            pools[side]=uniq
        row={"year":yr,"eligible":int(te.sum()),"policies":{}}
        for floor in floors:
            singles=[];extensions=[];config=[]
            for side in (0,1):
                head,add,union=choose(pools[side],y[val],side,floor,minsel)
                single=np.zeros(te.sum(),bool) if head is None else head["t"].copy()
                ext=single.copy()
                for p in add:ext|=p["t"]
                singles.append(single);extensions.append(ext)
                config.append({"side":side,"head":head["config"] if head else None,"add":[p["config"] for p in add],"validation_extended":m(y[val],union,side)})
            q={"config":config}
            for lane,pair in [("single",singles),("extended",extensions)]:
                S,B=pair;bs=B&~S;ss=S&~B
                totals[str(floor)][lane].append((y[te],bs,ss))
                q[lane]={"conflicts":int((B&S).sum()),"metrics":score(y[te],bs,ss,np.ones(te.sum(),bool))}
            row["policies"][str(floor)]=q
        annual.append(row)
    agg={}
    for floor,lanes in totals.items():
        agg[floor]={}
        for lane,ls in lanes.items():
            assert ls,(tf,floor,lane)
            Y,B,S=[np.concatenate([v[i] for v in ls]) for i in range(3)]
            agg[floor][lane]=score(Y,B,S,np.ones(len(Y),bool))
    report={"tf":tf,"n":len(Y),"fits":fits,"rule_evaluations":rules,"aggregate":agg,"annual":annual,
      "limits":["Same-fold single vs extension comparison, not exact historic benchmark reproduction","Accuracy floors apply to retrospective policy selection, not guarantees on evaluation or post-conflict precision","Missing qualifying policy means WAIT","Historical sample reused; macro cutoff April 2026, release lag proxies","No DXY intraday, entries or live actions"]}
    O.joinpath(f"r27-coverage-{tf}.json").write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!="annual"}),flush=True)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--lane",required=True,choices=["1h","4h","macro"]);a=p.parse_args().lane
    if a=="macro":
        src=macro_sources()
        for tf in ["1D","1W"]:run(tf,src)
    else:run(a,None)
