"""RIZAN Snowball S6: XAUUSD-only and EUR-independent BUY/SELL seed signal research.

Public third-party Dukascopy-derived bid/ask M1 pinned at immutable commit.
NOT FP Markets; NOT a native Frozen V1 matched replay; NO LIVE authority.
FXCM EURUSD S5 is a different venue and cannot be fused into a matched wallet.
"""
from __future__ import annotations
import argparse,hashlib,io,json,time
from pathlib import Path
import numpy as np,pandas as pd,requests
import snowball_s5_fxcm_grid as eur

REPO="3650326613-png/dukascopy_xauusd_1m_data"
PIN="1d8e4c008fe177be455f6de05f5057ebdde901ae"
BASE=f"https://raw.githubusercontent.com/{REPO}/{PIN}/xauusd"
OUT=Path("artifacts/snowball_s6")
OUT.mkdir(parents=True,exist_ok=True)
STAGES=(100,125,250,1000)
# 0.01 standard gold lot = 1 troy ounce is *only* a research assumption.
MIN_OZ=1.0
LEVERAGE=200
MARGIN_CAP=.5
RISK_CAP=.08
SLIP_USD=.05
ROUNDTRIP_FEE_USD=.10
FAMILIES=eur.FAMILIES
EXPECTED=eur.EXPECTED_MODELS

def source(year:int):
    if year not in range(2012,2026):
        raise ValueError("No annual XAU test outside 2012–2025")
    pieces={};provenance={};download=requests.Session()
    for side in ("bid","ask"):
        months=[];digest={}
        for month in range(1,13):
            path=f"{side}/m1/xauusd_{side}_m1_{year}_{month:02d}.csv"
            url=f"{BASE}/{path}"
            response=None
            for retry in range(3):
                try:
                    response=download.get(url,timeout=(10,80))
                    response.raise_for_status()
                    break
                except requests.RequestException:
                    if retry==2:raise
                    time.sleep(1+retry)
            raw=response.content
            if not 200_000<len(raw)<6_000_000:raise ValueError(f"Malformed {url}: {len(raw)}")
            d=pd.read_csv(io.BytesIO(raw))
            assert list(d.columns)==["timestamp","open","high","low","close"],(url,d.columns.tolist())
            t=pd.to_datetime(pd.to_numeric(d.pop("timestamp"),errors="raise").to_numpy(np.int64),
                             unit="ms",utc=True)
            assert len(t)>25000 and t.is_monotonic_increasing and t.is_unique
            assert t[0].year==year and t[0].month==month and t[-1].month==month
            d.index=t
            months.append(d.rename(columns={"open":"o","high":"h","low":"l","close":"c"}).astype(float))
            digest[str(month)]=hashlib.sha256(raw).hexdigest()
        x=pd.concat(months).sort_index()
        assert x.index.is_unique
        pieces[side]=x
        provenance[side]=digest
    bid=pieces["bid"];ask=pieces["ask"]
    common=bid.index.intersection(ask.index)
    mismatch=max(len(bid),len(ask))-len(common)
    assert len(common)>=.99*max(len(bid),len(ask)),(year,len(bid),len(ask))
    bid=bid.loc[common];ask=ask.loc[common]
    valid=np.isfinite(bid.to_numpy()).all(axis=1)&np.isfinite(ask.to_numpy()).all(axis=1)
    valid &= (bid.l>0)&(ask.l>0)
    valid &= (bid.l<=bid[["o","c"]].min(axis=1))&(bid.h>=bid[["o","c"]].max(axis=1))
    valid &= (ask.l<=ask[["o","c"]].min(axis=1))&(ask.h>=ask[["o","c"]].max(axis=1))
    # Crossed quotes are not executable; reject instead of changing their sign.
    spread=ask.o-bid.o
    valid &= (spread>=0)&(spread<15)
    ny=bid.index.tz_convert("America/New_York")
    closed=(ny.dayofweek==5)|((ny.dayofweek==4)&(ny.hour>=17))|(
            (ny.dayofweek==6)&(ny.hour<18))
    valid &= ~closed
    bid=bid.loc[valid];ask=ask.loc[valid]
    stationary=(bid.h==bid.l)&(bid.o==bid.c)&bid.c.eq(bid.c.shift())
    flat3=stationary.rolling(3,min_periods=3).sum()>=3
    bid=bid.loc[~flat3];ask=ask.loc[~flat3]
    x=pd.DataFrame({"bo":bid.o,"bh":bid.h,"bl":bid.l,"bc":bid.c,
                    "ao":ask.o,"ah":ask.h,"al":ask.l,"ac":ask.c})
    assert x.index.is_monotonic_increasing and x.index.is_unique
    assert len(x)>180000,(year,len(x))
    assert (x.index.asi8%60_000_000_000==0).all()
    active_spread=x.ao-x.bo
    prov={"provider":"THIRD_PARTY_DUKASCOPY_DERIVED_XAU_M1_BID_ASK",
          "venue_not_FP_Markets":True,"year":year,"repository":REPO,"commit":PIN,
          "monthly_sha256":provenance,"bid_ask_unmatched_censored":int(mismatch),
          "bad_or_closed_minutes_removed":int(len(common)-len(bid)),
          "stale_quote_minutes_censored":int(flat3.sum()),
          "observed_spread_median_usd_per_oz":float(active_spread.median()),
          "observed_spread_p95_usd_per_oz":float(active_spread.quantile(.95)),
          "rows":len(x),"first":str(x.index[0]),"last":str(x.index[-1]),
          "approximate_minimum_oz":MIN_OZ,
          "no_native_execution_or_capacity_proof":True}
    return x,prov

def outcome(d,m,events,side,hold,stop_atr,tp_r):
    """Return for all eligible signal decisions; deterministic stop-first OHLC M1."""
    empty=(np.array([],dtype=int),np.array([],dtype=float),np.array([],dtype=float),
           np.array([],dtype=bool),np.array([],dtype=float),
           {t:np.array([],dtype=bool) for t in STAGES})
    if not len(events):return empty
    t=d.index.asi8//60_000_000_000
    dec=m.index.asi8//60_000_000_000
    p=np.searchsorted(t,dec[events])
    safe=np.clip(p,0,len(t)-1)
    end=np.clip(p+hold-1,0,len(t)-1)
    gap=np.r_[0,np.cumsum(np.diff(t)!=1)]
    ok=(p+hold<=len(t))&(t[safe]==dec[events])&(
        t[end]==dec[events]+hold-1)&(gap[end]==gap[safe])
    events=events[ok];p=p[ok]
    if not len(p):return empty
    a=d.to_numpy(float)
    atr=m.atr.to_numpy(float)
    anchor=(m.l if side==1 else m.h).to_numpy(float)
    ixout=[];base_out=[];stress_out=[];correct_out=[];mae_out=[]
    enabled={t:[] for t in STAGES}
    for group in np.array_split(np.arange(len(p)),max(1,(len(p)+255)//256)):
        ix=events[group];pos=p[group];s=atr[ix]
        entry=(a[pos,4]+SLIP_USD) if side==1 else (a[pos,0]-SLIP_USD)
        stop=(np.minimum(anchor[ix]-.05*s,entry-stop_atr*s) if side==1
             else np.maximum(anchor[ix]+.05*s,entry+stop_atr*s))
        risk=abs(entry-stop)
        feasible=(s>0)&(risk>0.05)&(risk<100)&np.isfinite(risk)&(
            a[pos,4]-a[pos,0]>=0)
        if not feasible.any():continue
        ix=ix[feasible];pos=pos[feasible]
        entry=entry[feasible];stop=stop[feasible];risk=risk[feasible]
        path=a[pos[:,None]+np.arange(hold)[None,:]]
        if side==1:
            target=entry+tp_r*risk
            stopped=path[:,:,2]<=stop[:,None]
            touched=path[:,:,1]>=target[:,None]
            op=path[:,:,0]
            raw_end=path[:,-1,3]
            end_price=raw_end-SLIP_USD
        else:
            target=entry-tp_r*risk
            stopped=path[:,:,5]>=stop[:,None]
            touched=path[:,:,6]<=target[:,None]
            op=path[:,:,4]
            raw_end=path[:,-1,7]
            end_price=raw_end+SLIP_USD
        exit_event=stopped|touched
        first=exit_event.argmax(axis=1)
        anyhit=exit_event.any(axis=1)
        r=np.arange(len(ix))
        hitstop=anyhit&stopped[r,first]
        hit_tp=anyhit&~hitstop
        if side==1:
            stop_exit=np.minimum(op[r,first]-SLIP_USD,stop-SLIP_USD)
            tp_exit=target-SLIP_USD
            adverse=np.where(np.arange(hold)[None,:]<=np.where(anyhit,first,hold-1)[:,None],
                path[:,:,2],np.inf).min(axis=1)
            mae=np.maximum(0.,entry-adverse)/risk
        else:
            stop_exit=np.maximum(op[r,first]+SLIP_USD,stop+SLIP_USD)
            tp_exit=target+SLIP_USD
            adverse=np.where(np.arange(hold)[None,:]<=np.where(anyhit,first,hold-1)[:,None],
                path[:,:,5],-np.inf).max(axis=1)
            mae=np.maximum(0.,adverse-entry)/risk
        out=np.where(hitstop,stop_exit,np.where(hit_tp,tp_exit,end_price))
        signed=(out-entry)*side
        # Stress costs double slippage and commission, holding the same OHLC
        # stop path. This underestimates any changes in stop trigger timing.
        pnl=(signed-ROUNDTRIP_FEE_USD)/risk
        pnl_stress=(signed-ROUNDTRIP_FEE_USD-SLIP_USD*2-ROUNDTRIP_FEE_USD)/risk
        correct=(raw_end-entry)*side>0
        ixout.extend(ix.tolist());base_out.extend(pnl.tolist())
        stress_out.extend(pnl_stress.tolist())
        correct_out.extend(correct.tolist());mae_out.extend(mae.tolist())
        for balance in STAGES:
            admissible=(risk+ROUNDTRIP_FEE_USD+2*SLIP_USD)*MIN_OZ<=RISK_CAP*balance
            admissible &= entry*MIN_OZ/LEVERAGE<=MARGIN_CAP*balance
            enabled[balance].extend(admissible.tolist())
    return (np.asarray(ixout,dtype=int),np.asarray(base_out,dtype=float),
        np.asarray(stress_out,dtype=float),np.asarray(correct_out,dtype=bool),
        np.asarray(mae_out,dtype=float),{k:np.asarray(v,dtype=bool) for k,v in enabled.items()})

def metric(p,s,c,mae,signals):
    n=len(p)
    if not n:
        return {"n":0,"signals":int(signals),"gross_profit_R":0.,"gross_loss_R":0.,
            "net_R":0.,"net_stress_R":0.,"wins":0,"direction_correct":0,"mae_R":0.}
    return {"n":int(n),"signals":int(signals),"gross_profit_R":float(p[p>0].sum()),
      "gross_loss_R":float(-p[p<0].sum()),"net_R":float(p.sum()),"net_stress_R":float(s.sum()),
      "wins":int((p>0).sum()),"stress_wins":int((s>0).sum()),
      "direction_correct":int(c.sum()),"mae_R":float(mae.sum())}

def run(year):
    d,prov=source(year)
    m=eur.features(d)
    mins=m.index.asi8//60_000_000_000
    hr=m.hour_wib.to_numpy()
    sessions={"ALL":np.ones(len(m),bool),
       "EUR_CORE_WIB":(hr>=14)&(hr<19),
       "US_SESSION_WIB":(hr>=19)|(hr<1)}
    trends=m.trend.to_numpy()
    results=[]
    for side in eur.SIDES:
      for lookback in eur.LOOKBACKS:
       for fam in FAMILIES:
        sig=eur.family_signal(m,side,lookback,fam)
        event=np.flatnonzero(sig)
        for hold in eur.HOLDS:
         for smult in eur.STOPS:
          for tp in eur.TARGETS:
           a,net,stress,correct,mae,feasible=outcome(d,m,event,side,hold,smult,tp)
           where={int(i):j for j,i in enumerate(a)}
           for gate in eur.REGIMES:
            mask=np.ones(len(m),bool) if gate=="ANY" else (
                trends==side if gate=="H4_WITH" else trends==-side)
            for sess,session_mask in sessions.items():
             signal_indices=np.flatnonzero(sig&mask&session_mask)
             good=np.array([i for i in signal_indices if i in where],dtype=int)
             distinct=eur.greedy(good,hold,mins)
             indices=np.array([where[int(i)] for i in distinct],dtype=int)
             stage_results={}
             for cash in STAGES:
                 j=indices[feasible[cash][indices]]
                 stage_results[str(cash)]=metric(net[j],stress[j],correct[j],mae[j],len(signal_indices))
             name=(f"{fam}|{'BUY' if side==1 else 'SELL'}|LB{lookback}|{gate}|{sess}|"
                   f"H{hold}|SL{smult:g}|TP{tp:g}")
             results.append({"config":name,"family":fam,"side":"BUY" if side==1 else "SELL",
              "lookback":lookback,"gate":gate,"session":sess,
              "hold":hold,"stop_atr":smult,"tp_R":tp,
              "stages":stage_results})
    assert len(results)==EXPECTED,(year,len(results))
    report={"version":"SNOWBALL_S6_DUKA_XAU_SOURCE_FIXED_1","year":year,
      "provider":prov,"configs":EXPECTED,"rows":results,"research_only":True,
      "execution_authority":False,"frozen_v1_ledger_parity":False,
      "limitations":["Dukascopy-derived third-party M1; not FP Markets and not Frozen V1 exact tape",
       "Price path uses M1 OHLC with stop-first ambiguous handling",
       "1oz min lot,1:200 leverage,8% risk,50% margin per account are hypothetical",
       "Tier results are independent signal admissibility at fixed cash values, not compounding",
       "Fixed $0.05/oz per side slippage, fixed $0.10/oz roundtrip fee plus vendor spreads",
       "Stress cost 2x changes net without re-running stop-trigger event sequence",
       "OHLC M1 cannot reproduce broker order queue, funding, roll, latency or market impact",
       "Historically researched years not a pristine holdout, no LIVE/trading modifications"]}
    f=OUT/f"s6_xau_{year}.json";f.write_text(json.dumps(report,allow_nan=False))
    s=[r for r in results if r["stages"]["100"]["n"]>=40]
    best=sorted(s,key=lambda q:q["stages"]["100"]["net_stress_R"]/q["stages"]["100"]["n"],
                reverse=True)[:4]
    print("S6_YEAR",json.dumps({"year":year,"configs":EXPECTED,
       "source":{k:v for k,v in prov.items() if k!="monthly_sha256"},
       "n_configs_with_40_or_more_staged_100":len(s),
       "top_DIAGNOSTIC_ONLY":[{"name":q["config"],"stages":q["stages"]} for q in best]},
       allow_nan=False),flush=True)

def agg(root):
    years=range(2012,2026);entries={};source_quality={}
    for y in years:
        src=list(Path(root).rglob(f"s6_xau_{y}.json"))
        assert len(src)==1,(y,src)
        data=json.loads(src[0].read_text())
        assert data["year"]==y and data["configs"]==EXPECTED
        entries[y]={x["config"]:x for x in data["rows"]}
        source_quality[str(y)]={k:v for k,v in data["provider"].items() if k!="monthly_sha256"}
    configs=set(entries[2012])
    assert len(configs)==EXPECTED and all(set(entries[y])==configs for y in years)
    def fold(k,years,cash):
        q=[entries[y][k]["stages"][str(cash)] for y in years]
        n=sum(z["n"] for z in q)
        net=sum(z["net_R"] for z in q)
        stress=sum(z["net_stress_R"] for z in q)
        win=sum(z["wins"] for z in q)
        profit=sum(z["gross_profit_R"] for z in q)
        loss=sum(z["gross_loss_R"] for z in q)
        return {"n":n,"avg_R":net/n if n else None,"stress_avg_R":stress/n if n else None,
          "pf":profit/loss if loss else None,
          "winrate":win/n if n else None,
          "positive_years_base":sum(z["net_R"]>0 and z["n"]>=10 for z in q),
          "positive_years_stress":sum(z["net_stress_R"]>0 and z["n"]>=10 for z in q),
          "years":len(q),"yearly_n":[z["n"] for z in q]}
    bycash={};inspect=[]
    for cash in STAGES:
        trained=[];validated=[]
        for k in sorted(configs):
            t=fold(k,range(2012,2019),cash)
            if (t["n"]<90 or t["stress_avg_R"] is None or t["stress_avg_R"]<=.025 or
                t["pf"] is None or t["pf"]<1.12 or t["positive_years_stress"]<5):continue
            v=fold(k,range(2019,2023),cash)
            e=fold(k,range(2023,2026),cash)
            passed=(v["n"]>=45 and v["stress_avg_R"] is not None and
               v["stress_avg_R"]>.015 and v["pf"] is not None and v["pf"]>=1.08 and
               v["positive_years_stress"]>=3)
            trained.append({"config":k,"train":t,"validation":v,
               "retrospective":e,"passed_validation":bool(passed)})
            if passed:validated.append(k)
        bycash[str(cash)]={"training_qualified":len(trained),
          "validation_qualified":len(validated),
          "retrospective_positive":sum(x["passed_validation"] and x["retrospective"]["n"]>=25
              and x["retrospective"]["stress_avg_R"] is not None and
              x["retrospective"]["stress_avg_R"]>0 for x in trained)}
        inspect+=sorted(trained,key=lambda x:x["train"]["stress_avg_R"],reverse=True)[:12]
    result={"study":"RIZAN_S6_XAU_DUKASCOPY_2012_2025",
       "version":"S6_DUKA_1","independent_policy_count":EXPECTED,
       "model_year_count":EXPECTED*14,
       "stages_cash_levels_usd":list(STAGES),
       "train":"2012-2018","validate":"2019-2022","retrospective":"2023-2025",
       "staged_counts":bycash,
       "diagnostic_top_only":inspect,
       "source":source_quality,
       "source_is_frozen_v1":False,
       "native_ledger_parity":False,"matched_eur_xau_wallet_evaluated":False,
       "terminal_balance_to_10b_evaluated":False,
       "research_only":True,"execution_authority":False}
    (OUT/"s6_xau_aggregate.json").write_text(json.dumps(result,indent=2,allow_nan=False))
    print("S6_AGGREGATE",json.dumps({k:v for k,v in result.items()
       if k not in ("diagnostic_top_only","source")},allow_nan=False),flush=True)
    print("S6_TOP_DIAGNOSTIC",json.dumps(inspect[:4],allow_nan=False),flush=True)

if __name__=="__main__":
    cli=argparse.ArgumentParser()
    cli.add_argument("--year",type=int)
    cli.add_argument("--aggregate",action="store_true")
    cli.add_argument("--root",default="/tmp/snowball_s6")
    cli.add_argument("--selftest",action="store_true")
    args=cli.parse_args()
    if args.selftest:
        eur.selftest()
        assert EXPECTED==3456
        print("S6_SELFTEST",json.dumps({"configs":EXPECTED,"cash_stages":STAGES,"source":REPO}))
    elif args.aggregate:agg(args.root)
    elif args.year is not None:run(args.year)
    else:cli.error("Specify --year, --selftest or --aggregate")
