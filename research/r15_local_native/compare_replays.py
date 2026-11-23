"""Paired native result comparison, including orders/cash/equity rather than only PnL."""
from pathlib import Path
import argparse,gzip,json,hashlib

def read(p):return json.loads(gzip.decompress(Path(p).read_bytes()))
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def compare(a,b):
    names=('Ledger','OrderLedger','CashLedger','EquityCurve')
    match={n:digest(a[n])==digest(b[n]) for n in names}
    return {'ledger_equality':match,'all_ledger_streams_equal':all(match.values()),'baseline_summary':a['Summary'],'candidate_summary':b['Summary'],'terminal_change':b['Summary']['EndingBalance']-a['Summary']['EndingBalance'],'terminal_ratio':b['Summary']['EndingBalance']/a['Summary']['EndingBalance'],'floating_DD_change_pp':b['Summary']['MaxEquityDDPct']-a['Summary']['MaxEquityDDPct'],'guard_audit':b.get('GrowthGuardAudit'),'native_synthetic_M1':True,'broker_tick_certified':False,'live_changes':False}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('baseline');p.add_argument('candidate');p.add_argument('--output');a=p.parse_args();r=compare(read(a.baseline),read(a.candidate));s=json.dumps(r,indent=2,allow_nan=False)+'\n'
 if a.output:Path(a.output).write_text(s)
 print(s)
