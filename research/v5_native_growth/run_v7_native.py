"""Execute V5 on a restored, isolated native research workspace.
No broker, no production I/O. Baseline must pass before challenger execution.
"""
import argparse, gzip, hashlib, json, math, os, subprocess
from pathlib import Path
H={"xau_2012_2026.csv":"defcbd64ab625156f7594f8a357591bc3d2fea2a0e8deb4c9144ae88e4e8fea7","eur_2012_2026.csv":"710f10ed97e709f48e284e79511981e4e85638deca6958a668908d6f418285c5","BTCUSD_M1.csv":"9257332636450a0c93d20c45757016ae359feb208d7b91ac82fac173a64f8c51"}
def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
    return h.hexdigest()
def main():
    p=argparse.ArgumentParser()
    for k in ("inputs","seed","dll","work"):p.add_argument("--"+k,type=Path,required=True)
    p.add_argument("--profiles",type=Path,default=Path(__file__).with_name("profiles.json"));p.add_argument("--dotnet",default="dotnet");p.add_argument("--limit",type=int,default=0);p.add_argument("--stress-top",type=int,default=4)
    a=p.parse_args();a.inputs=a.inputs.resolve();a.seed=a.seed.resolve();a.dll=a.dll.resolve();a.work=a.work.resolve()
    if any(sha(a.inputs/k)!=v for k,v in H.items()):raise SystemExit("EXACT_PRICE_IDENTITY_REQUIRED")
    tape=a.seed/"base3_symbol0.bin";assert tape.stat().st_size%40==0
    assert a.dll.is_file()
    a.work.mkdir(parents=True,exist_ok=False)
    profiles=json.loads(a.profiles.read_text())
    control=next(x for x in profiles if x["Id"] in ("V5_CONTROL","V6_CONTROL","V7_CONTROL"))
    masks=[7,1,2,4,3,6,5]
    for profile in profiles:
        cfg=profile["Seed"]
        for sid in range(3):
            if masks[cfg["Universe"]] & (1<<sid):
                f=a.seed/f'base{cfg["Base"]}_symbol{sid}.bin'
                assert f.stat().st_size>0 and f.stat().st_size%40==0, f
    (a.work/"macro_off.json").write_text("{}")
    env={k:v for k,v in os.environ.items() if not k.startswith(("RESEARCH_","R15_","BTC_SIGNAL_","BTC_FRIDAY_","BTC_SEVEN_","ADAPTIVE_GUARD","XAU_START_","RIZAN_REPLAY_"))}
    env.update(SEED_DATA=str(a.seed),BTC_INPUT=str(a.inputs/"BTCUSD_M1.csv"),MACRO_DATA=str(a.work/"macro_off.json"))
    def run(profs,way,cost,label):
        out=a.work/label;out.mkdir()
        conf=out/"profiles.json";conf.write_text(json.dumps(profs))
        e={**env,"RESEARCH_CONFIGS":str(conf),"RESEARCH_PATH":way,"RESEARCH_COST":str(cost)}
        result=out/"results.json"
        cmd=[a.dotnet,str(a.dll),str(a.inputs/"xau_2012_2026.csv"),str(a.inputs/"eur_2012_2026.csv"),str(result),"research","2019","2026"]
        with (out/"stdout.log").open("w") as f:subprocess.run(cmd,env=e,stdout=f,stderr=subprocess.STDOUT,check=True)
        rows=json.loads(result.read_text())
        assert len(rows)==len(profs)
        for r in rows:
            s=r["Summary"]
            assert s["ErrorCount"]==0 and s["OpenPositions"]==0 and not s["Quarantined"] and not s["AccountingBlock"] and s["TotalContributions"]==100
            receipt=Path(r["File"])
            if not receipt.is_absolute():receipt=Path.cwd()/receipt
            with gzip.open(receipt,"rt") as f:raw=json.load(f)
            assert len(raw["Ledger"])==s["Baskets"] and raw["Summary"]["EndingBalance"]==s["EndingBalance"]
            residual=100+math.fsum(t["Pnl"] for t in raw["Ledger"])-s["EndingBalance"]
            assert abs(residual)<.05,("CASH_CONSERVATION_FAILURE",residual)
            r["ReceiptSHA256"]=sha(receipt)
            r["LedgerResidualUSD"]=residual
        (out/"verified_receipts.json").write_text(json.dumps(rows,indent=2))
        return rows
    base=run([control],"B",1,"control_B1")[0]["Summary"]
    assert abs(base["EndingBalance"]-1662133293.0811067)<.01 and abs(base["MaxEquityDDPct"]-56.67209330213908)<1e-6 and base["Baskets"]==1047 and base["Orders"]==187560,"BASELINE_PARITY_FAILURE"
    print("BASELINE_PARITY",base["EndingBalance"],base["MaxEquityDDPct"],flush=True)
    candidates=[x for x in profiles if x["Id"]!=control["Id"]]
    if a.limit:candidates=candidates[:a.limit]
    ranked=[]
    for i,x in enumerate(candidates):
        r=run([x],"B",1,"challenger_"+str(i))[0];s=r["Summary"]
        ranked.append({"id":x["Id"],"balance":s["EndingBalance"],"dd":s["MaxEquityDDPct"],"baskets":s["Baskets"],"orders":s["Orders"],"observed_risk":s["MaxObservedOpenRiskPct"],"observed_margin":s["MaxObservedMarginPct"],"B1_candidate":s["EndingBalance"]>base["EndingBalance"] and s["MaxEquityDDPct"]<60})
        ranked.sort(key=lambda q:q["balance"],reverse=True)
        (a.work/"B1_ranked.json").write_text(json.dumps(ranked,indent=2))
    print("COMPLETED_B1",len(ranked),flush=True)
    # Compare against a newly executed same-path/same-cost control, never
    # against the favorable B1 reference under alternative assumptions.
    selected=[q for q in ranked if q["B1_candidate"]][:a.stress_top]
    byid={x["Id"]:x for x in profiles}
    stresses=[]
    for way,cost in [("A",1),("A",2),("B",2)] if selected else []:
        baseline=run([control],way,cost,f"stress_control_{way}{cost}")[0]["Summary"]
        for i,q in enumerate(selected):
            ss=run([byid[q["id"]]],way,cost,f"stress_{way}{cost}_{i}")[0]["Summary"]
            stresses.append({"id":q["id"],"path":way,"cost":cost,"balance":ss["EndingBalance"],"floating_dd":ss["MaxEquityDDPct"],"baseline_balance":baseline["EndingBalance"],"baseline_dd":baseline["MaxEquityDDPct"],"orders":ss["Orders"],"baskets":ss["Baskets"],"max_observed_open_risk_pct":ss["MaxObservedOpenRiskPct"],"max_observed_margin_pct":ss["MaxObservedMarginPct"],"passes":ss["EndingBalance"]>baseline["EndingBalance"] and ss["MaxEquityDDPct"]<60})
            (a.work/"stress_ranked.json").write_text(json.dumps(stresses,indent=2))
    for q in selected:
        checks=[z for z in stresses if z["id"]==q["id"]]
        q["all_four_path_cost_gate"]=len(checks)==3 and all(z["passes"] for z in checks)
        q["target_hit_B1"]=q["balance"]>=1e10
        q["target_hit_all_cases"]=q["all_four_path_cost_gate"] and q["target_hit_B1"] and all(z["balance"]>=1e10 for z in checks)
    (a.work/"B1_ranked.json").write_text(json.dumps(ranked,indent=2))
    print("COMPLETED_V7",json.dumps({"challenger_B1":len(ranked),"stress_challenger_cases":len(stresses),"control_cases":1+(3 if selected else 0),"target_all_cases":[q["id"] for q in selected if q["target_hit_all_cases"]]}))
if __name__=="__main__":main()
