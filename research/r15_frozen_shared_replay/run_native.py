"""Run original or adapter source in the same native-source wallet; never broker IO."""
import argparse,json,os,subprocess,hashlib,gzip
from pathlib import Path

SEED=dict(Base=3,Sl=2,Tp=3,Hold=2,Trend=2,Session=0,Risk=5,Universe=1,Day=1,Threshold=3,Direction=1,SeedOnly=False,HandoffEquity=125)

def run(args):
    root=Path(args.runtime);inputs=Path(args.inputs);out=root/args.mode;out.mkdir(parents=True,exist_ok=True)
    if args.year:
        cases=[dict(Id=f'{args.mode}_Y{args.year}',Mode='off',Year=args.year,Seed=SEED,GrowthRisk=20.75,Addon=None)]
    else:
        cases=[dict(Id=f'{args.mode}_Y{y}',Mode='off',Year=y,Seed=SEED,GrowthRisk=20.75,Addon=None) for y in range(2019,2027)]
        cases.append(dict(Id=f'{args.mode}_continuous',Mode='off',Year=2019,EndYear=2026,Seed=SEED,GrowthRisk=20.75,Addon=None))
    if args.continuous_only:cases=cases[-1:]
    (out/'profiles.json').write_text(json.dumps(cases,indent=2))
    env=dict(os.environ,SEED_DATA=str(root/'seed'),BTC_INPUT=str(inputs/'BTCUSD_M1.csv'),
        RESEARCH_CONFIGS=str(out/'profiles.json'),MACRO_DATA=str(root/'unused_macro_off.json'),
        RESEARCH_COST=str(args.cost),RESEARCH_PATH=args.path,R15_ADDON_MODE=args.mode,
        R15_SIGNAL_DIR=str(root/'signals'),DOTNET_CLI_TELEMETRY_OPTOUT='1')
    # Explicitly clear inherited research overrides that could change the control.
    for name in ('BTC_SIGNAL_CACHE','BTC_SEVEN_DAY','RESEARCH_NEXT_M1','ADAPTIVE_GUARD','XAU_START_UTC','RIZAN_REPLAY_SLOW'):
        env.pop(name,None)
    command=[args.dotnet,args.dll,str(inputs/'xau_2012_2026.csv'),str(inputs/'eur_2012_2026.csv'),str(out/'results.json'),'research','2019','2026']
    with (out/'run.log').open('w') as f:p=subprocess.run(command,env=env,stdout=f,stderr=subprocess.STDOUT)
    print('R15_NATIVE_EXIT',args.mode,p.returncode,flush=True)
    if p.returncode:
        print((out/'run.log').read_text()[-5000:]);raise SystemExit(p.returncode)
    records=json.loads((out/'results.json').read_text())
    for r in records:
        summary=r['Summary'];file=Path(r['File'])
        with gzip.open(file,'rt') as f:data=json.load(f)
        print('R15_SUMMARY',json.dumps(dict(case=r['Profile']['Id'],path=r['Path'],cost=r['Cost'],
            balance=summary['EndingBalance'],floating_DD=summary['MaxEquityDDPct'],baskets=summary['Baskets'],
            sparse=data.get('SparseAudit'),seed=data.get('SeedAudit'),errors=summary['ErrorCount'],
            ledger_sha256=hashlib.sha256(file.read_bytes()).hexdigest())),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--dotnet',required=True);p.add_argument('--dll',required=True)
    p.add_argument('--runtime',required=True);p.add_argument('--inputs',required=True)
    p.add_argument('--mode',choices=['off','pds','breakout','both'],required=True);p.add_argument('--year',type=int)
    p.add_argument('--continuous-only',action='store_true');p.add_argument('--path',default='B');p.add_argument('--cost',default=1,type=int)
    run(p.parse_args())
