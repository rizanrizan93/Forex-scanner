#!/usr/bin/env python3
"""Exploratory, reproducible BTC/XAU bottom-formation study.
READ-ONLY research. No brokerage credentials or execution. Python stdlib only.
Methodology intentionally fixed before viewing R4 outputs. Do not overclaim OOS.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import math
import os
import statistics
import urllib.request
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
SOURCES = {
    "BTC": {
        "url": "https://raw.githubusercontent.com/alessiostomeo/btc-cycle-data/b57f460fab1afb82705eb813cee2ef4afb1f6848/bitstamp/1h/BTCUSD_bitstamp_hourly_2012-2026.csv.gz",
        "lookback_h4": 2190, "dd": 0.35, "cost_roundtrip": 0.002,
        "stop_buffer": 0.0075, "max_stop_pct": 0.12, "split_year": 2020,
    },
    "XAU": {
        "url": "https://raw.githubusercontent.com/FeziweMelvin/XAUUSD-Gold-Price/310bc3cdd7e55bc338c1f55738abab92aa745d0a/XAU_1h_data.csv",
        "lookback_h4": 1560, "dd": 0.15, "cost_roundtrip": 0.001,
        "stop_buffer": 0.0025, "max_stop_pct": 0.045, "split_year": 2016,
    },
}
MODELS = ["SWEEP", "MSS", "HL_SWEEP_STOP", "HL_LOCAL_STOP", "HL_BOS_LOCAL_STOP"]
HORIZON_DAYS = 30
WATCH_COOLDOWN_DAYS = 45
MAX_MSS_BARS = 48
MAX_HL_BARS = 72
MAX_BOS_BARS = 48


@dataclass
class Bar:
    dt: datetime
    o: float
    h: float
    l: float
    c: float
    count: int = 1


def parse_time(raw: str, asset: str) -> datetime:
    raw = raw.strip()
    if asset == "XAU":
        # Source's broker clock lacks explicit timezone. Used as a synthetic clock,
        # not a verified UTC timestamp. Source-relative H4 candle alignment only.
        return datetime.strptime(raw, "%Y.%m.%d %H:%M").replace(tzinfo=UTC)
    if raw.isdecimal():
        n = int(raw)
        if n > 10**12:
            n /= 1000
        return datetime.fromtimestamp(n, tz=UTC)
    raw = raw.replace(" ", "T")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def download_and_parse(asset: str, cfg: dict):
    req = urllib.request.Request(cfg["url"], headers={"User-Agent": "RIZAN-Research-Bottom-R4/1.0"})
    with urllib.request.urlopen(req, timeout=120) as response:
        data = response.read()
    if cfg["url"].endswith(".gz"):
        data = gzip.decompress(data)
    decoded = data.decode("utf-8-sig")
    delimiter = ";" if asset == "XAU" else ","
    reader = csv.DictReader(io.StringIO(decoded), delimiter=delimiter)
    rows, bad, duplicates, gaps = [], 0, 0, 0
    last = None
    for r in reader:
        try:
            d = parse_time(r["Date"] if asset == "XAU" else r["datetime_utc"], asset)
            o, h, l, c = [float(r[key].strip()) for key in (("Open", "High", "Low", "Close") if asset == "XAU" else ("open", "high", "low", "close"))]
            if not (o > 0 and l > 0 and h >= max(o,c,l) and l <= min(o,c,h)):
                bad += 1
                continue
            if last and d <= last:
                if d == last:
                    duplicates += 1
                else:
                    raise ValueError("Unsorted H1 timestamp")
                continue
            if last and d-last > timedelta(hours=10):
                gaps += 1
            rows.append(Bar(d,o,h,l,c))
            last = d
        except (ValueError, KeyError, TypeError) as exc:
            bad += 1
    if len(rows) < 15000:
        raise ValueError(f"{asset}: insufficient valid H1 rows: {len(rows)}")
    if duplicates:
        raise ValueError(f"{asset}: duplicate H1 timestamps: {duplicates}")
    if bad > 0.01 * len(rows):
        raise ValueError(f"{asset}: too many invalid rows: {bad}")
    return rows, {"h1_rows":len(rows),"h1_first":rows[0].dt.isoformat(),"h1_last":rows[-1].dt.isoformat(),"bad_rows":bad,"gap_over_10h":gaps}


def build_h4(hourly: list[Bar]):
    grouped = []
    current = None
    for b in hourly:
        bucket = b.dt.replace(hour=(b.dt.hour // 4)*4, minute=0, second=0, microsecond=0)
        if current is None or bucket != current.dt:
            current = Bar(bucket,b.o,b.h,b.l,b.c,1)
            grouped.append(current)
        else:
            current.h=max(current.h,b.h)
            current.l=min(current.l,b.l)
            current.c=b.c
            current.count += 1
    partial=sum(b.count<3 for b in grouped)
    # Exclude sparse weekend/edge buckets: they create spurious pivots and sweeps.
    grouped=[b for b in grouped if b.count>=3]
    if len(grouped)<3000: raise ValueError("Insufficient full-ish H4 candles")
    return grouped, {"h4_rows":len(grouped),"excluded_h4_under_3_h1":partial,"h4_first":grouped[0].dt.isoformat(),"h4_last":grouped[-1].dt.isoformat()}


def rolling_peaks(a: list[Bar], lookback: int):
    q=deque()
    peaks=[float("nan")]*len(a)
    for i,b in enumerate(a):
        while q and q[0] < i-lookback:
            q.popleft()
        if q:
            peaks[i]=a[q[0]].h
        while q and a[q[-1]].h<=b.h:
            q.pop()
        q.append(i)
    return peaks


def highest(a,first,last):
    return max(x.h for x in a[first:last+1])


def lowest(a,first,last):
    return min(x.l for x in a[first:last+1])


def sma(a,i,period=20):
    return sum(b.c for b in a[i-period+1:i+1])/period


def atr(a,i,n=14):
    tr=[]
    for j in range(i-n+1,i+1):
        b=a[j]
        p=a[j-1].c
        tr.append(max(b.h-b.l, abs(b.h-p), abs(b.l-p)))
    return statistics.fmean(tr)


def watches(a,cfg):
    peaks=rolling_peaks(a,cfg["lookback_h4"])
    out=[]
    last_watch=None
    for i in range(max(cfg["lookback_h4"],60),len(a)-200):
        b=a[i]
        if last_watch and b.dt-last_watch < timedelta(days=WATCH_COOLDOWN_DAYS):
            continue
        p=peaks[i]
        if not math.isfinite(p) or b.c/p-1 > -cfg["dd"]:
            continue
        prior_low=lowest(a,i-30,i-1)
        close_location=(b.c-b.l)/(b.h-b.l) if b.h>b.l else 0
        if b.l < prior_low and b.c > prior_low and close_location >= 0.60:
            out.append(i)
            last_watch=b.dt
    return out


def no_break(a,start,end,low):
    return all(x.l >= low for x in a[start:end+1])


def find_formations(a,watch_idx,cfg):
    w=a[watch_idx]
    mss=None
    for k in range(watch_idx+1,min(len(a)-200,watch_idx+MAX_MSS_BARS+1)):
        if not no_break(a,watch_idx+1,k,w.l):break
        b=a[k]
        if b.c>highest(a,k-6,k-1) and b.c>sma(a,k,20) and b.c>b.o:
            mss=k
            break
    if mss is None: return {"MSS":None,"HL":None,"BOS":None,"PIVOT":None}
    pivot=None
    confirm=None
    initial_atr=atr(a,mss)
    for p in range(mss+2,min(len(a)-200,mss+MAX_HL_BARS)):
        c=p+2
        if not no_break(a,watch_idx+1,c,w.l):break
        z=a[p]
        if (z.l<min(a[p-1].l,a[p-2].l)
                and z.l<=min(a[p+1].l,a[p+2].l)
                and z.l>w.l*(1+(0.003 if cfg["dd"]==0.35 else 0.001))
                and z.l<highest(a,mss,p-1)-0.5*initial_atr
                and a[c].c>z.l):
            pivot,confirm=p,c
            break
    if confirm is None: return {"MSS":mss,"HL":None,"BOS":None,"PIVOT":None}
    neckline=highest(a,mss,confirm)
    bos=None
    for k in range(confirm+1,min(len(a)-200,confirm+MAX_BOS_BARS+1)):
        if not no_break(a,pivot+1,k,a[pivot].l):break
        if a[k].c>neckline and a[k].c>sma(a,k,20):
            bos=k
            break
    return {"MSS":mss,"HL":confirm,"BOS":bos,"PIVOT":pivot}


def entry_spec(a,w,f,model):
    if model=="SWEEP":return (w,a[w].l)
    if model=="MSS":return (f["MSS"],a[w].l)
    if model=="HL_SWEEP_STOP":return (f["HL"],a[w].l)
    if model=="HL_LOCAL_STOP":return (f["HL"],a[f["PIVOT"]].l if f["PIVOT"] is not None else None)
    if model=="HL_BOS_LOCAL_STOP":return (f["BOS"],a[f["PIVOT"]].l if f["PIVOT"] is not None else None)
    raise ValueError(model)


def simulate(a,w,trigger,stop_base,cfg):
    if trigger is None or stop_base is None: return None
    if trigger+1>=len(a):return None
    start=a[trigger+1].dt
    deadline=start+timedelta(days=HORIZON_DAYS)
    if a[-1].dt<deadline: return None
    fee=cfg["cost_roundtrip"]
    entry=a[trigger+1].o*(1+fee/2)
    stop=stop_base*(1-cfg["stop_buffer"])
    risk=entry-stop
    if risk<=0 or risk/entry>cfg["max_stop_pct"]:
        return {"rejected":"stop_risk_cap","risk_pct":100*risk/entry}
    tp=entry+2*risk
    exit_price=None
    why=None
    close_idx=None
    min30=float("inf")
    for j in range(trigger+1,len(a)):
        b=a[j]
        if b.dt>deadline:break
        min30=min(min30,b.l)
        if why is None:
            if b.o<=stop:
                exit_price=b.o
                why="SL_GAP"
                close_idx=j
            elif b.l<=stop:
                exit_price=stop
                why="SL"
                close_idx=j
            elif b.h>=tp:
                exit_price=tp
                why="TP"
                close_idx=j
    if why is None:
        j=max(trigger+1,min(len(a)-1,j-1))
        exit_price=a[j].c
        why="TIMEOUT"
        close_idx=j
    result_R=(exit_price*(1-fee/2)-entry)/risk
    return {"rejected":None,"entry_datetime":start.isoformat(),"trigger_datetime":a[trigger].dt.isoformat(),
            "stop":round(stop,4),"entry":round(entry,4),"tp":round(tp,4),
            "stop_risk_pct":100*risk/entry,"outcome":why,"net_R":result_R,
            "elapsed_days_to_trigger":(a[trigger].dt-a[w].dt).total_seconds()/86400,
            "new_low_30d":min30<a[w].l,
            "MAE_30d_pct":100*(min30/entry-1),
            "exit_datetime":a[close_idx].dt.isoformat()}


def aggregate(events,watch_count):
    traded=[e for e in events if e.get("rejected") is None]
    n=len(traded)
    if not n:return {"watch_candidates":watch_count,"n":0,"coverage_pct":0,"rejected_by_risk":sum(e.get("rejected")=="stop_risk_cap" for e in events)}
    avg=lambda k:statistics.fmean(e[k] for e in traded)
    winners=[max(0,e["net_R"]) for e in traded]
    losers=[max(0,-e["net_R"]) for e in traded]
    gross_loss=sum(losers)
    pf=sum(winners)/gross_loss if gross_loss>0 else None
    return {"watch_candidates":watch_count,"n":n,"coverage_pct":round(n/watch_count*100,1) if watch_count else 0,
        "rejected_by_risk":sum(e.get("rejected")=="stop_risk_cap" for e in events),
        "tp":sum(e["outcome"]=="TP" for e in traded),
        "sl":sum(e["outcome"] in ("SL","SL_GAP") for e in traded),
        "timeout":sum(e["outcome"]=="TIMEOUT" for e in traded),
        "mean_net_R":round(avg("net_R"),3),
        "median_net_R":round(statistics.median(e["net_R"] for e in traded),3),
        "profit_factor_R":round(pf,3) if pf is not None else None,
        "new_low_30d_pct":round(100*sum(e["new_low_30d"] for e in traded)/n,1),
        "avg_MAE_30d_pct":round(avg("MAE_30d_pct"),2),
        "avg_stop_risk_pct":round(avg("stop_risk_pct"),2),
        "avg_confirmation_lag_days":round(avg("elapsed_days_to_trigger"),2)}


def run_asset(asset,cfg):
    rows,quality=download_and_parse(asset,cfg)
    h4,extra=build_h4(rows)
    quality.update(extra)
    del rows
    candidate_idx=watches(h4,cfg)
    formations={idx:find_formations(h4,idx,cfg) for idx in candidate_idx}
    study={}
    for model in MODELS:
        ev=[]
        for w in candidate_idx:
            t,stop_base=entry_spec(h4,w,formations[w],model)
            if t is None:continue
            trial=simulate(h4,w,t,stop_base,cfg)
            if trial:
                ev.append({"watch_datetime":h4[w].dt.isoformat(),
                    "split":"development" if h4[w].dt.year<cfg["split_year"] else "validation", **trial})
        study[model]={}
        for split in ("development","validation"):
            count=sum((h4[i].dt.year<cfg["split_year"])==(split=="development") for i in candidate_idx)
            es=[e for e in ev if e["split"]==split]
            study[model][split]={"summary":aggregate(es,count),"trades":es}
    return {"asset":asset,"quality":quality,"source_url":cfg["url"],
        "watch_count":len(candidate_idx),"studies":study}


def paired_watch_audit(payload):
    # Descriptive comparisons on identical watch events. Models can have
    # distinct entry/exit times, and selecting only confirmed events biases
    # the paired sample; this is NOT an unbiased causal effect estimate.
    out=[]
    for asset in payload["assets"]:
        studies=asset["studies"]
        for split in ("development","validation"):
            baseline={e["watch_datetime"]:e for e in studies["SWEEP"][split]["trades"]
                      if e.get("rejected") is None}
            for model in MODELS[1:]:
                confirmed=[e for e in studies[model][split]["trades"]
                           if e.get("rejected") is None and e["watch_datetime"] in baseline]
                delta=[e["net_R"]-baseline[e["watch_datetime"]]["net_R"] for e in confirmed]
                out.append({
                    "asset":asset["asset"],"split":split,"model":model,"matched":len(delta),
                    "avg_delta_R":round(statistics.fmean(delta),3) if delta else None,
                    "fraction_better_pct":round(100*sum(z>0 for z in delta)/len(delta),1) if delta else None,
                    "years":sorted(set(int(e["watch_datetime"][:4]) for e in confirmed))
                })
    return out


def render_report(payload):
    head=[
       "# RIZAN — Bottom Formation Detection R4 (H4)",
       "",
       "**READ-ONLY exploratory study. No claim of deployable alpha or confirmed bottom.**",
       "",
       "The same H4 sweep-watch events are compared across five candidate entry policies. No future bars are used for entry: H4 swing lows need two subsequent H4 closes for confirmation before they become actionable.",
       "",
       "Gold feed has an unverified broker clock; H4 bins use source clock with UTC assigned synthetically. BTC is Bitstamp USD. H4 buckets with fewer than 3 H1 observations are dropped.",
       "",
       f"Scan: trailing {SOURCES['BTC']['lookback_h4']} H4 bars BTC or {SOURCES['XAU']['lookback_h4']} H4 bars gold; minimum drawdown 35% BTC or 15% gold. A watch is a sell-side sweep of the prior 30 H4 bars, close back above that low, close-location >=60%. Candidate watch cooldown: {WATCH_COOLDOWN_DAYS} calendar days.",
       "",
       "MSS: within 48 H4 bars without violating the sweep low, bullish close above the previous six H4 highs and H4 SMA20. Higher low: swing pivot with 2 left/2 right candles, above sweep low by a buffer and following >=0.5 ATR(14) pullback; actionable only after the second right candle closes. BOS: reclaim neckline after HL confirmation.",
       "",
       "Stop options: below initial sweep low (SWEEP/MSS/HL_SWEEP_STOP) or confirmed higher-low pivot (HL_LOCAL_STOP/HL_BOS_LOCAL_STOP). Buffers: 0.75% BTC; 0.25% gold. Reject entries with risk >12% BTC or >4.5% gold. Targets 2R; 30-calendar-day horizon. Gap-through stop fills at worse open; same-bar SL precedence. Fees assumed 0.20% BTC / 0.10% gold round trip. No funding, slippage, swaps, capital/risk sizing, or leverage modeled.",
       "",
       "Temporal split BTC validation from 2020; gold validation from 2016. This is an exploratory time split, not virgin out-of-sample: model design followed R2/R3 observations and selection has multiple-testing risk.",
       "",
       "| Asset | Model | Split | Watches | Trades | Coverage | TP | SL | Mean net R | False-bottom 30d | Avg stop % | Avg entry delay days |",
       "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    ]
    for a in payload["assets"]:
        for model,splits in a["studies"].items():
            for split,data in splits.items():
                s=data["summary"]
                head.append("| "+ " | ".join(str(x) for x in [
                  a["asset"],model,split,s["watch_candidates"],s["n"],s["coverage_pct"],
                  s.get("tp","-"),s.get("sl","-"),s.get("mean_net_R","-"),
                  s.get("new_low_30d_pct","-"),s.get("avg_stop_risk_pct","-"),
                  s.get("avg_confirmation_lag_days","-")])+" |")
    head += ["", "## Paired watch-event audit (descriptive, selected matches)",
             "Difference in realized net R between confirmed entry and immediate SWEEP entry for identical watch-date events. Not a causal test; non-confirming watch events do not contribute.",
             "",
             "| Asset | Split | Model | Matched watches | Mean ΔR versus SWEEP | Improved fraction | Years represented |",
             "|---|---|---|---:|---:|---:|---|"]
    for row in payload["paired_audit"]:
        head.append("| "+" | ".join(str(z) for z in [
             row["asset"],row["split"],row["model"],row["matched"],
             row["avg_delta_R"] if row["avg_delta_R"] is not None else "-",
             row["fraction_better_pct"] if row["fraction_better_pct"] is not None else "-",
             ",".join(map(str,row["years"])) if row["years"] else "-"])+" |")
    head += ["", "## Data quality"]
    for a in payload["assets"]:
        q=a["quality"]
        head += [f"- {a['asset']}: {q['h1_rows']} hourly bars, {q['h4_rows']} H4 bars, first {q['h1_first']}, last {q['h1_last']}, excluded sparse H4={q['excluded_h4_under_3_h1']}, >10h gaps={q['gap_over_10h']}. {a['source_url']}"]
    head += [
       "",
       "## Validity cautions",
       "- Entry models condition on the same watch candidates but may trade at distinct dates; coverage and risk cap alter sample composition. Compare both coverage and expectancy; never rank by win rate alone.",
       "- Consecutive 45-day watch windows share macro regimes; independent episode counts are lower than trade counts.",
       "- The 'new low' metric refers to the first sweep low and considers all bars within 30 days after entry, even following an SL/TP.",
       "- High/low OHLC does not identify intra-candle execution order; stop wins ambiguous candles. A true live fill requires broker bid/ask spread data.",
       "- H4 signals are based on *source* historical feeds; not validated against FP Markets cTrader quotations.",
       "- On-chain (BTC) and macro DXY/US2Y/US10Y/real yields (gold) have not been included because point-in-time series and release timestamps are needed to avoid leakage.",
       "- This dataset does not verify real-time November 2026 bottom signals. Do not use results for live execution.",
       "",
       "## Next gate",
       "Only proceed to prospective H1/H4 forward shadow after cross-broker data QA, episode-held-out validation, walk-forward parameter stability, and explicit drawdown/coverage constraints. Frozen V1 and cBots untouched.",
       ""
    ]
    return "\n".join(head)


def main():
    output={"protocol":"bottom_r4_h4_v1","generated_utc":datetime.now(UTC).isoformat(),
        "assets":[],"models":MODELS}
    for asset,cfg in SOURCES.items():
        output["assets"].append(run_asset(asset,cfg))
    output["paired_audit"]=paired_watch_audit(output)
    os.makedirs("research_outputs/bottom_r4",exist_ok=True)
    with open("research_outputs/bottom_r4/results.json","w") as f:
        json.dump(output,f,indent=2)
    report=render_report(output)
    with open("research_outputs/bottom_r4/report.md","w") as f:
        f.write(report+"\n")
    print(report)

if __name__ == "__main__":
    main()
