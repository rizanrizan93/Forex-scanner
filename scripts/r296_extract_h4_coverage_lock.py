"""Extract and freeze original R29.1 H4 BUY annual policies, never retune.
Input is the immutable artifact from GitHub Actions run 45165585427.
Research-only: this writes documentation, NOT an order or trading engine.
"""
import hashlib,json
from pathlib import Path

SRC=Path("artifacts/r296_source/r291-event-4h.json")
OUT=Path("research/RIZAN_R291_H4_BUY_COVERAGE_FROZEN_20261123.json")
EXPECTED={"2024":(143,83),"2025":(176,108),"2026":(13,8)}
def extract():
    raw=SRC.read_bytes()
    doc=json.loads(raw)
    if doc["tf"]!="H4" or not doc["version"].startswith("R29_1_"):
        raise ValueError("R296_ORIGINAL_ARTIFACT_CONTRACT")
    if (doc["aggregate"]["BUY"]["n"],doc["aggregate"]["BUY"]["correct"])!=(332,199):
        raise ValueError("R296_ORIGINAL_AGGREGATE_MISMATCH")
    if abs(float(doc["aggregate"]["BUY"]["accuracy"])-199/332)>1e-5:
        raise ValueError("R296_AGGREGATE_ACC_FORGED")
    years={}
    for row in doc["annual"]:
        yr=str(row["year"])
        if yr not in EXPECTED:continue
        selected=row["sides"]["BUY"]["selected"]
        if not selected:raise ValueError("R296_POLICY_MISSING_"+yr)
        result=row["sides"]["BUY"]["evaluated"]
        n,k=EXPECTED[yr]
        if (result["n"],result["correct"])!=(n,k):
            raise ValueError("R296_EVALUATION_MISMATCH_"+yr)
        policy={key:selected[key] for key in ("model","group","threshold","gate")}
        if policy["model"] not in ("ridge","hgb") or policy["group"] not in (
            "event_geometry","event_bos_context"
        ):
            raise ValueError("R296_INVALID_POLICY_"+yr)
        if policy["gate"] not in (
            "all","trend_follow","countertrend","vol_high","vol_low",
            "trend_highvol","bos_displacement","sweep_reversal",
            "displacement","trend_pullback","trend_impulse","range_rejection",
            "compression_release","strong_directional_pressure",
            "london","london_bos","london_sweep"
        ):
            raise ValueError("R296_INVALID_GATE_"+yr)
        validation=selected["selection"]
        if validation["n"]<35 or validation["correct"]>validation["n"]:
            raise ValueError("R296_INVALID_VALIDATION_"+yr)
        years[yr]={
            "evaluation_year":int(yr),
            "validation_year":int(yr)-1,
            "policy":policy,
            "selection_validation":validation,
            "evaluation":result,
        }
    if set(years)!=set(EXPECTED):raise ValueError("R296_MISSING_FOLDS")
    lock={
        "id":"RIZAN_R291_H4_BUY_HIGH_COVERAGE_HISTORICAL_FROZEN_20261123",
        "symbol":"XAUUSD","timeframe":"H4","side":"BUY",
        "source_run_id":45165585427,"source_artifact_id":14812894583,
        "source_artifact_name":"r291-event-4h",
        "source_json_sha256":hashlib.sha256(raw).hexdigest(),
        "strategy":"R29_1_EVENT_STRUCTURE_PREDECLARED_20261123",
        "target":"sign of next completed H4 candle close-minus-current close",
        "historical_pooled":{"n":332,"correct":199,"accuracy":199/332,
                             "net_mean_usd_oz":doc["aggregate"]["BUY"].get("net_mean_after_assumed_cost_usd_oz"),
                             "assumed_cost_usd_oz":0.7},
        "annual_policies":years,
        "live_policy_year":2026,
        "research_only":True,"execution_authority":False,
        "execution_influence":False,
        "forward_validated":False,
        "forexscanner_mode":"SIDE_BY_SIDE_SHADOW_NOT_ENTRY_PERMISSION",
        "warning":[
            "332 cumulative signals use different yearly selected policies, not a single frozen model",
            "2026 frozen fold generated only 13 historical BUY signals vs 23 for R29.2",
            "2026 R29.1 8/13 BUY net mean -3.4232 USD/oz after assumed $0.70/oz cost",
            "59.94% historic pooled score is NOT statistically established >60% or validated live",
            "This is a frequency-diversification historical candidate; forward signal count not guaranteed",
            "Strict no-order read-only publisher and closed broker H4 candle only",
        ],
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(lock,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"id":lock["id"],"sha256":lock["source_json_sha256"],
        "policies":{k:v["policy"] for k,v in years.items()},
        "validation_2025":years["2026"]["selection_validation"],
        "evaluations":{k:(v["evaluation"]["n"],v["evaluation"]["correct"]) for k,v in years.items()}},
        default=str),flush=True)
    return lock
if __name__=="__main__":extract()
