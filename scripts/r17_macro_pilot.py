"""R17: macro/technical matched-sample pilot, direction only.
Daily FRED observations are deliberately delayed by 2 weekdays, not proven
historical vintages. SF Fed FOMC event-date shocks available next UTC day
plus a conservative weekday lag; no pre-release prediction claimed.
No production integration, trade execution, or forward-validation claim.
"""
import io,json,hashlib,itertools
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np,pandas as pd,requests
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from r14_multitimeframe_direction import load_tf
from r16_direction_complexity import features
from r15_direction_tournament import score
from r10_million import wilson
O=Path("artifacts");O.mkdir(exist_ok=True)
SERIES=["DGS2","DGS10","DFII10","DTWEXBGS"]
FOMC="https://www.frbsf.org/wp-content/uploads/USMPD.xlsx"
def get(url):
    r=requests.get(url,timeout=(8,20),headers={"User-Agent":"Mozilla/5.0 research data retrieval"})
    r.raise_for_status();return r.content
def daily_macro():
    parts=[];meta={}
    for s in SERIES:
      url=f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={s}&cosd=2010-01-01"
      try:
        raw=get(url);a=pd.read_csv(io.BytesIO(raw));date=pd.to_datetime(a.iloc[:,0],utc=True)
        v=pd.Series(pd.to_numeric(a[s],errors="coerce").to_numpy(),index=date).dropna().sort_index()
        assert len(v)>1000 and v.index.max().year>=2025
        f=pd.DataFrame(index=v.index)
        for k in [1,3,5,10,20]:
            f[f"{s}_{k}"]=v.pct_change(k)*100 if s=="DTWEXBGS" else v.diff(k)
        f.index=f.index+pd.offsets.BDay(2)
        parts.append(f);meta[s]={"n":len(v),"first":str(v.index.min()),"last":str(v.index.max()),"sha256":hashlib.sha256(raw).hexdigest(),"url":url}
      except Exception as e:meta[s]={"error":repr(e),"url":url}
    if len(parts)<2:
        print(json.dumps({"fred_failed":meta,"fallback":"US Treasury XML"}),flush=True)
        parts,treasury=treasury_fallback();meta["treasury_fallback"]=treasury
    O.joinpath("r17-source-manifest.json").write_text(json.dumps({"macro":meta},indent=2))
    assert len(parts)>=2, "Insufficient verified macro series; inspect source manifest"
    return parts,meta
def treasury_fallback():
    # Official Treasury document feed, no keys. Independent alternate to FRED.
    base="https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
    def fetch(task):
        typ,year=task
        url=f"{base}?data={typ}&field_tdr_date_value={year}"
        try:
            raw=get(url);root=ET.fromstring(raw);rows=[]
            for e in root.iter():
                if e.tag.split("}")[-1]!="properties":continue
                rec={k.tag.split("}")[-1]:k.text for k in e}
                date=rec.get("NEW_DATE")
                if not date:continue
                if typ=="daily_treasury_yield_curve":
                    rows.append({"date":date,"DGS2":rec.get("BC_2YEAR"),"DGS10":rec.get("BC_10YEAR")})
                else:
                    rows.append({"date":date,"DFII10":rec.get("TC_10YEAR",rec.get("BC_10YEAR"))})
            if not rows:raise ValueError("No parsed observations")
            return typ,year,rows,{"url":url,"n":len(rows),"sha256":hashlib.sha256(raw).hexdigest()}
        except Exception as e:return typ,year,[],{"url":url,"error":repr(e)}
    tasks=list(itertools.product(["daily_treasury_yield_curve","daily_treasury_real_yield_curve"],range(2010,2027)))
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(fetch,tasks))
    meta={"requests":[{"type":typ,"year":yr,**m} for typ,yr,_,m in results]}
    parts=[]
    for s in ["DGS2","DGS10","DFII10"]:
        rows=[{"date":r["date"],"value":r.get(s)} for _,_,arr,_ in results for r in arr if s in r]
        if not rows:continue
        z=pd.DataFrame(rows);z.index=pd.to_datetime(z.date,utc=True,errors="coerce").dt.normalize()
        v=pd.to_numeric(z.value,errors="coerce").dropna();v=v[v.index.notna()].sort_index();v=v[~v.index.duplicated(keep="last")]
        if len(v)<1000 or v.index.max().year<2025:continue
        # Prevent silently treating missing years as valid prolonged forward fill.
        if set(range(2012,2027))-set(v.index.year):continue
        feat=pd.DataFrame({f"{s}_{k}":v.diff(k) for k in [1,3,5,10,20]})
        feat.index=feat.index+pd.offsets.BDay(2)
        parts.append(feat)
        meta[s]={"n":len(v),"first":str(v.index.min()),"last":str(v.index.max()),"kind":"Treasury par yield, not FRED feed"}
    return parts,meta
def date_column(a):
    for c in a.columns:
        if str(c).strip().lower() in ("date","eventdate","event date","meeting date","fomc date"):
            return c
    raise ValueError("Date column absent: "+repr(list(a.columns)))
def fomc():
    raw=get(FOMC);book=pd.ExcelFile(io.BytesIO(raw))
    # Use combined monetary events, not combined+statements+press to avoid double count.
    sheet=next((s for s in book.sheet_names if "monetary" in s.lower() and "event" in s.lower()),None)
    if sheet is None:raise ValueError("Combined events absent: "+repr(book.sheet_names))
    a=book.parse(sheet)
    dc=date_column(a)
    columns={str(c).strip().upper():c for c in a.columns}
    col=columns.get("UST2Y")
    if col is None:raise ValueError("UST2Y absent "+repr(list(a.columns)))
    dates=pd.to_datetime(a[dc],errors="coerce",utc=True)
    vals=pd.to_numeric(a[col],errors="coerce")
    e=pd.Series(vals.to_numpy(),index=dates).dropna()
    e=e[e.index.notna()].sort_index();e=e[~e.index.duplicated(keep="last")]
    assert len(e)>50 and e.index.max().year>=2025
    # Delay complete event to two weekdays after event date: explicitly not event spike.
    e.index=e.index.normalize()+pd.offsets.BDay(2)
    idx=pd.date_range("2010-01-01",e.index.max()+pd.Timedelta(days=90),freq="D",tz="UTC")
    shocks=e.groupby(level=0).sum().reindex(idx,fill_value=0.)
    f=pd.DataFrame(index=idx)
    for n in [1,3,5,10,20,40]:
        f[f"fomc_decay_{n}"]=shocks.ewm(halflife=n,adjust=False).mean()
    return f,{"sheet":sheet,"column":str(col),"n":len(e),"first_available":str(e.index.min()),"last_available":str(e.index.max()),"sha256":hashlib.sha256(raw).hexdigest(),"url":FOMC}
def met(y,p,cut):
    return score(y,p>=cut,p<.5 if cut==.5 else p<=1-cut,np.ones(len(y),bool))
def rank(m,n):
    if min(m["BUY"]["n"],m["SELL"]["n"])<n:return -1
    return min(m["BUY"]["wilson_lower95"],m["SELL"]["wilson_lower95"])
def align(parts,times,index):
    vals=[]
    for p in parts:
        q=p.reindex(times,method="ffill")
        q.index=index;vals.append(q)
    return pd.concat(vals,axis=1)
def run():
    parts,meta=daily_macro()
    try:
        fp,fmeta=fomc();parts.append(fp)
    except Exception as e:fmeta={"error":repr(e)}
    print(json.dumps({"macro_sources":meta,"fomc":fmeta}),flush=True)
    O.joinpath("r17-source-manifest.json").write_text(json.dumps({"macro":meta,"fomc":fmeta},indent=2))
    result={}
    for tf in ["1h","4h","1D","1W"]:
        d,z,_,y,valid,times=load_tf(tf)
        p=features(z)
        if tf in ("1D","1W"):p=p.drop(columns=[c for c in p if c.startswith("hour_")])
        m=align(parts,times,d.index)
        valid &= p.notna().all(axis=1).to_numpy() & m.notna().all(axis=1).to_numpy()
        xx={"technical":p,"macro":m,"hybrid":pd.concat([p,m],axis=1)}
        mat={k:x.to_numpy(float) for k,x in xx.items()}
        mature=pd.Series(times,index=d.index).shift(-1)
        pred={k:[] for k in xx};annual={k:[] for k in xx};nrule=0
        for yr in (range(2022,2027) if tf in ("1h","4h") else range(2018,2027)):
            b=pd.Timestamp(f"{yr}-01-01",tz="UTC");vstart=b-pd.DateOffset(years=1);end=b+pd.DateOffset(years=1)
            va=valid&(times>=vstart)&(times<b)&(mature<b).to_numpy()
            te=valid&(times>=b)&(times<end)&(mature<end).to_numpy()
            minval={"1h":60,"4h":30,"1D":20,"1W":8}[tf]
            if min(va.sum(),te.sum())<minval*2:continue
            for k,x in mat.items():
                best=None
                for years,C in itertools.product([3,6,10],[.01,.1,1.]):
                    tr=valid&(times>=vstart-pd.DateOffset(years=years))&(mature<vstart).to_numpy()
                    if tr.sum()<{"1h":500,"4h":200,"1D":150,"1W":60}[tf] or len(np.unique(y[tr]))<2:continue
                    mod=make_pipeline(StandardScaler(),LogisticRegression(C=C,max_iter=500))
                    mod.fit(x[tr],y[tr]);pv=mod.predict_proba(x[va])[:,1];pt=mod.predict_proba(x[te])[:,1]
                    for cut in [.5,.52,.55,.58,.60,.65]:
                        nrule+=1;v=met(y[va],pv,cut);q=rank(v,minval)
                        if q>=0 and (best is None or (q,v["coverage"])>best[0]):
                            best=((q,v["coverage"]),years,C,cut,pt)
                if best:
                    _,years,C,cut,pt=best
                    sig=np.where(pt>=cut,1,np.where(pt<.5 if cut==.5 else pt<=1-cut,0,-1))
                    conf={"years":years,"C":C,"threshold":cut}
                else:sig=np.full(te.sum(),-1);conf=None
                pred[k].append((y[te],sig))
                annual[k].append({"year":yr,"rule":conf,"evaluation":score(y[te],sig==1,sig==0,np.ones(te.sum(),bool))})
        agg={}
        for k,arr in pred.items():
            if arr:
                yy=np.concatenate([a for a,b in arr]);ss=np.concatenate([b for a,b in arr])
                agg[k]=score(yy,ss==1,ss==0,np.ones(len(yy),bool))
        result[tf]={"evaluations":nrule,"matched_sample":int(sum(len(a) for a,b in pred["technical"])),"aggregate":agg,"annual":annual}
        print(json.dumps({"tf":tf,"matched_sample":result[tf]["matched_sample"],"aggregate":agg}),flush=True)
    report={"version":"R17 pilot","results":result,"source_manifest":{"macro":meta,"fomc":fmeta},"limits":["FRED current vintage, approximated 2 business-day lag, no true PIT verification","Broad-dollar index DTWEXBGS is not DXY","FOMC UST2Y event-window change proxy, not direct surprise statistic, conservative two weekdays after date; if acquisition failed explicitly absent","CPI/NFP and other archived consensus news not yet included","Annual validation before evaluation, purged label maturity; historically reused, not fresh holdout","All three lanes identical matched samples; no entry zones, trade decisions or profit claims"]}
    O.joinpath("r17-macro-pilot.json").write_text(json.dumps(report,indent=2))
if __name__=="__main__":run()
