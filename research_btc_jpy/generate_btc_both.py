import pathlib,json,csv,itertools,sys
root=pathlib.Path(__file__).parent;seeds=json.loads((root/'BUYSELL_SEEDS.json').read_text())
out=pathlib.Path(sys.argv[1])
fields=['id','seed_id','source','tf_minutes','family','lookback','threshold_index','trend_filter','session_utc','stop_atr','tp_R','hold_bars','add_stages','breakeven_R','vol_gate','rsi_gate','weekday_gate','close_location_gate','daily_trend_gate','risk','margin_fraction','short_risk','short_margin']
count=0
with out.open('w') as f:
 w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
 for sid,s in enumerate(seeds,1):
  for br,sr,bm,sm in itertools.product([round(i/100,2) for i in range(10,31)],[.01,.02,.03,.04,.06,.08,.10,.12,.15,.20,.25,.30],[.5,.75,.85,.9,.95],[.1,.3,.5,.75,.95]):
   count+=1;w.writerow(dict(s,id=count,seed_id=sid,risk=br,margin_fraction=bm,short_risk=sr,short_margin=sm))
assert count==630000,count
print('EXACT_CONFIGURATIONS',count,'SEEDS',len(seeds))
