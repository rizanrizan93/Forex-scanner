"""S5 frozen-results forensic audit, no new parameter fitting or deployment."""
import argparse,hashlib,json
from collections import Counter,defaultdict
from pathlib import Path

def main(root):
  rr={};meta={}
  for year in range(2012,2026):
    a=list(Path(root).rglob(f"s5_eurusd_{year}.json"))
    assert len(a)==1,(year,a)
    d=json.loads(a[0].read_text())
    assert d["year"]==year and len(d["rows"])==3456
    rr[year]={x["config"]:x for x in d["rows"]}
    meta[year]=d["provider"]
  keys=sorted(rr[2012])
  assert all(set(rr[y])==set(keys) for y in rr)
  source={}
  for y,v in meta.items():
    missing=v["missing_weeks"]
    internal=[w for w in missing if 2<=w<=51]
    source[y]={"bars":v["bars"],"weeks":v["week_count"],
      "missing_weeks":missing,"internal_missing_weeks":internal,
      "calendar_span_complete":v["full_calendar_year"],
      "strict_full_history":bool(v["full_calendar_year"] and not internal),
      "empty_source_weeks":v.get("empty_csv_weeks",[])}
  def fold(k,ys):
    data=[rr[y][k] for y in ys]
    n=sum(x["n"] for x in data)
    gain=sum(x["profit_R"] for x in data)
    loss=sum(x["loss_R"] for x in data)
    net=sum(x["net_R"] for x in data)
    return {"n":n,"avg_R":net/n if n else None,
       "pf":gain/loss if loss else None,
       "positive_years":sum(x["net_R"]>0 and x["n"]>=12 for x in data),
       "wins":sum(x["wins"] for x in data),
       "win_rate":sum(x["wins"] for x in data)/n if n else None,
       "yearly_n":[x["n"] for x in data]}
  diag=[];criteria=Counter();fingerprints=Counter()
  for k in keys:
    t=fold(k,range(2012,2019))
    v=fold(k,range(2019,2023))
    e=fold(k,range(2023,2026))
    if t["n"]>=200:criteria["train_n_ge_200"]+=1
    if t["n"]>=200 and t["avg_R"] is not None and t["avg_R"]>0:criteria["train_positive_mean"]+=1
    if t["n"]>=200 and t["pf"] is not None and t["pf"]>=1.12:criteria["train_pf_ge_1_12"]+=1
    if t["n"]>=200 and t["positive_years"]>=5:criteria["train_positive_years_ge5"]+=1
    if t["n"]>=200 and t["avg_R"] is not None and t["avg_R"]>.04 and t["pf"] is not None and t["pf"]>=1.12 and t["positive_years"]>=5:criteria["passes_predeclared_train_all"]+=1
    digest=hashlib.sha256(json.dumps([
      [rr[y][k][name] for name in ("n","wins","net_R","mae_R")]
      for y in range(2012,2026)],sort_keys=True).encode()).hexdigest()
    fingerprints[digest]+=1
    if t["n"]>=200:
      diag.append({"config":k,"train":t,"validation":v,"retrospective":e})
  diag=sorted(diag,key=lambda z:(z["train"]["avg_R"] or -999),reverse=True)
  report={
    "study":"S5_FXCM_3456_CONFIG_14YEAR_FROZEN_OUTPUT_AUDIT",
    "research_only":True,"live_permission":False,"frozen_v1_ledger_parity":False,
    "calendar_source_status":source,
    "strict_full_source_years":[y for y,v in source.items() if v["strict_full_history"]],
    "partial_or_holey_source_years":[y for y,v in source.items() if not v["strict_full_history"]],
    "total_parameter_configurations":len(keys),
    "distinct_annual_outcome_fingerprints":len(fingerprints),
    "parameter_config_duplicates_by_annual_outcome":len(keys)-len(fingerprints),
    "predeclared_gate_breakdown":dict(criteria),
    "top_training_DIAGNOSTIC_ONLY":diag[:25],
    "winner_selected":False,
    "caveats":["Diagnostics use existing 2012–2025 annual results; no re-fitting/deployment",
      "2023 source has an empty valid gzip week; later years may have other missing internal weeks",
      "Unit-R from independent signal opportunities, not native $100 wallet or $10B portfolio",
      "No verified stress-cost replay; no ability to infer maximum floating DD",
      "Parameter configurations need not represent distinct trading behaviors",
      "Retrospective outcomes already inspected and not pristine holdout"]
  }
  p=Path("artifacts/snowball_s5/s5_forensics.json")
  p.parent.mkdir(parents=True,exist_ok=True)
  p.write_text(json.dumps(report,indent=2,allow_nan=False))
  print("S5_FORENSICS",json.dumps({k:v for k,v in report.items()
    if k not in ("top_training_DIAGNOSTIC_ONLY","calendar_source_status")},allow_nan=False),flush=True)
  print("S5_TOP_TRAIN_DIAGNOSTIC",json.dumps(diag[:5],allow_nan=False),flush=True)

if __name__=="__main__":
  a=argparse.ArgumentParser();a.add_argument("--root",default="/tmp/snowball_s5")
  q=a.parse_args();main(q.root)
