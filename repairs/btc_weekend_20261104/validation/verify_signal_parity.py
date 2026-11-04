from pathlib import Path
import json,csv,collections,datetime
import argparse
parser=argparse.ArgumentParser();parser.add_argument('xau_csv',type=Path);args=parser.parse_args()
R=Path(__file__).resolve().parents[1];C=R/'validation/reference'
native=json.loads((R/'validation/XAU_NATIVE_SIGNALS.json').read_text())
original=json.loads((C/'original_xau_tape.json').read_text())['Signals']
native_original=json.loads((R/'validation/XAU_NATIVE_SIGNALS.json.original.json').read_text())
on={p['AtUtc']:p for p in native_original};oe={p['At']:p for p in original}
assert on.keys()==oe.keys()
assert all(on[k]['Side']==oe[k]['Side'] and max(abs(on[k][f]-oe[k][f]) for f in ['Atr','Anchor'])<1e-8 for k in oe)
expected=json.loads((C/'expected_xau_tape.json').read_text())['Signals']
times={p['AtUtc'] for p in native if p['Side']==-1};flags={}
with args.xau_csv.open() as f:
 for row in csv.DictReader(f):
  at=row['timestamp'].replace(' ','T').replace('+00:00','Z')
  if at in times:flags[at]=row['sell_ok']=='1'
merged={p['AtUtc']:dict(At=p['AtUtc'],Side=p['Side'],Distance=p['Distance'],Atr=p['Atr'],Anchor=p['Anchor'],Fast=0,Slow=0) for p in native_original};raw_buy=raw_sell=0
for p in native:
 at=p['AtUtc']
 if p['Side']==-1 and not flags.get(at,False):continue
 if p['Side']==1:raw_buy+=1
 else:raw_sell+=1
 merged.setdefault(at,dict(At=at,Side=p['Side'],Distance=p['Distance'],Atr=p['Atr'],Anchor=p['Anchor'],Fast=0,Slow=0))
exp={p['At']:p for p in expected}
assert merged.keys()==exp.keys(),(len(merged),len(exp),list(exp.keys()-merged.keys())[:3],list(merged.keys()-exp.keys())[:3])
assert all(exp[k]['Side']==merged[k]['Side'] for k in exp)
diff=max(abs(exp[k][f]-merged[k][f]) for k in exp for f in ['Atr','Anchor']);assert diff<1e-8,diff
report=dict(pass_check=True,native_ohlc_extras=len(native),native_buy_raw=raw_buy,native_sell_after_frozen_csv_admission=raw_sell,merged_signals=len(merged),original_signals=len(original),original_signals_generated_from_native_frozen_core=True,timestamp_side_match=True,max_atr_anchor_difference=diff,full_historical_input=True,macro_vintage_certified=False,native_live_feed_is_runtime_gate=True,native_broker_financial_replay=False)
(R/'SIGNAL_PARITY.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
