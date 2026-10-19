"""Recover validated rows; execute only missing IDs. No trading connections."""
import pathlib, pandas as pd, hashlib, json, sys
root=pathlib.Path.cwd(); shard=int(sys.argv[2]); out=root/'result'
old=root/'checkpoint'/f'RIZAN-BTC-BOTH56-SHARD-{shard}'/'RESULTS.csv'
q=pd.read_csv(old); configs=pd.read_csv(root/'CONFIGS.csv')
expected=configs[(configs.id-1)%4==shard]
assert len(q)==111825 and q.id.nunique()==len(q)
assert set(q.id)==set(expected[expected.id<=447300].id)
assert q['case'].eq('BASE').all()
params=list(configs.columns)
a=q.set_index('id')[params[1:]].sort_index(); b=expected.set_index('id').loc[a.index,params[1:]]
pd.testing.assert_frame_equal(a,b,check_dtype=False,atol=1e-14,rtol=1e-14)
if sys.argv[1]=='prepare':
 out.mkdir(exist_ok=True)
 q.to_csv(out/'ORIGINAL_PARTIAL_RESULTS.csv.gz',index=False,compression='gzip')
 missing=expected[~expected.id.isin(q.id)]
 assert len(missing)==45675
 missing.to_csv(root/'REMAINING.csv',index=False)
 (out/'RECOVERY.json').write_text(json.dumps(dict(checkpoint_run=39273886250,checkpoint_commit='f3e97d82547b403be0845bee43bb43046da72e29',shard=shard,reused=len(q),remaining=len(missing),original_results_sha256=hashlib.sha256(old.read_bytes()).hexdigest()),indent=2))
else:
 fresh=pd.read_csv(out/'RESULTS.csv')
 assert len(fresh)==45675 and not set(fresh.id)&set(q.id)
 full=pd.concat([q,fresh]).sort_values('id')
 assert len(full)==157500 and full.id.nunique()==157500 and set(full.id)==set(expected.id)
 pd.testing.assert_frame_equal(full.set_index('id')[params[1:]],expected.set_index('id')[params[1:]],check_dtype=False,atol=1e-14,rtol=1e-14)
 fresh.to_csv(out/'RESUMED_RESULTS.csv.gz',index=False,compression='gzip')
 full.to_csv(out/'RESULTS.csv.gz',index=False,compression='gzip')
 (out/'RESULTS.csv').unlink()
 print('VERIFIED_COMPLETE',len(full),'REUSED',len(q),'NEW',len(fresh),flush=True)
