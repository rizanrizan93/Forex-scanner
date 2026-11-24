"""Execute V5 on a restored, isolated native research workspace.
No broker, no production I/O. Baseline must pass before challenger execution.
"""
import argparse, hashlib, json, os, subprocess
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
    p.add_argument("--dotnet",default="dotnet");p.add_argument("--limit",type=int,default=0)
    a=p.parse_args();a.inputs=a.inputs.resolve();a.seed=a.seed.resolve();a.dll=a.dll.resolve();a.work=a.work.resolve()
    if any(sha(a.inputs/k)!=v for k,v in H.items()):raise SystemExit("EXACT_PRICE_IDENTITY_REQUIRED")
    tape=a.seed/"base3_symbol0.bin";assert tape.stat().st_size%40==0
    assert a.dll.is_file()
    a.work.mkdir(parents=True,exist_ok=False)
    profiles=json.loads(Path(__file__).with_name("profiles.json").read_text())
    control=next(x for x in profiles if x["Id"]=="V5_CONTROL")
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
            assert s["ErrorCount"]==0 and s["OpenPositions"]==0 and not s["Quarantined"] and s["TotalContributions"]==100
        return rows
    base=run([control],"B",1,"control_B1")[0]["Summary"]
    assert abs(base["EndingBalance"]-1662133293.0811067)<.01 and abs(base["MaxEquityDDPct"]-56.67209330213908)<1e-6 and base["Baskets"]==1047 and base["Orders"]==187560,"BASELINE_PARITY_FAILURE"
    print("BASELINE_PARITY",base["EndingBalance"],base["MaxEquityDDPct"],flush=True)
    candidates=[x for x in profiles if x["Id"]!="V5_CONTROL"]
    if a.limit:candidates=candidates[:a.limit]
    ranked=[]
    for i,x in enumerate(candidates):
        r=run([x],"B",1,"challenger_"+str(i))[0];s=r["Summary"]
        ranked.append({"id":x["Id"],"balance":s["EndingBalance"],"dd":s["MaxEquityDDPct"],"baskets":s["Baskets"],"orders":s["Orders"],"observed_risk":s["MaxObservedOpenRiskPct"],"observed_margin":s["MaxObservedMarginPct"],"B1_candidate":s["EndingBalance"]>base["EndingBalance"] and s["MaxEquityDDPct"]<60})
        ranked.sort(key=lambda q:q["balance"],reverse=True)
        (a.work/"B1_ranked.json").write_text(json.dumps(ranked,indent=2))
    print("COMPLETED_B1",len(ranked),"NOT A/B COST STRESS OR LIVE APPROVAL")
if __name__=="__main__":main()
