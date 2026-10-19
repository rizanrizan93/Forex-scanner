"""Merge disjoint direct-M1 shards without losing any configuration rows."""
import argparse,pathlib,json,gzip,shutil,hashlib,csv
import pandas as pd
def main():
 p=argparse.ArgumentParser();p.add_argument('symbol');p.add_argument('input');p.add_argument('output');a=p.parse_args()
 root=pathlib.Path(a.input);dest=pathlib.Path(a.output);dest.mkdir(parents=True,exist_ok=True)
 dirs=sorted(root.glob(f'{a.symbol}_*'))
 if len(dirs)!=5:raise AssertionError(f'Expected5shards,got{len(dirs)}')
 seen=set();allhash=set();frames=[];summary=None;sources=set();inputs=set();total_targets=0;total_dd=0;traincount=0;shardinfo=[]
 out=dest/f'results_{a.symbol}';out.mkdir(exist_ok=True);data=dest/'data';data.mkdir(exist_ok=True)
 header=None
 with open(out/'ALL_CONFIGURATIONS.csv','w') as w:
  for d in dirs:
   s=json.loads((d/'SUMMARY.json').read_text());sid=int(s['shard']);assert s['unique_configurations']==200000 and s['configuration_stream_size']==1000000
   if summary is None:summary=s.copy()
   else:assert all(s[k]==summary[k] for k in ['symbol','m1_rows','first','last'])
   inputs.add((d/'INPUT_SHA256.txt').read_text().split()[0]);sources.add((d/'SOURCE_SHA256.txt').read_text().split()[0])
   total_targets+=s['screen_target_count'];total_dd+=s['screen_target_dd50_count'];traincount+=s['train_pass_count']
   with gzip.open(d/'ALL_CONFIGURATIONS.csv.gz','rt') as f:
    h=f.readline()
    if header is None:header=h;w.write(h)
    else:assert header==h
    for row in csv.reader(f):
     cid=int(row[0]);assert 1<=cid<=1000000 and (cid-1)%5==sid and cid not in seen;seen.add(cid)
     # Tuple of exported active parameters, not floating point scores.
     signature=tuple(row[1:15]);assert signature not in allhash;allhash.add(signature)
     w.write(','.join(row)+'\n')
   v=pd.read_csv(d/'M1_VALIDATION.csv');v['shard']=sid;frames.append(v)
   for f in d.glob('candidate_*'):
    if (out/f.name).exists():raise AssertionError('candidate_id_collision')
    shutil.copy2(f,out/f.name)
   for f in d.glob('ENGINE_FIXTURES.log'):shutil.copy2(f,out/f'ENGINE_FIXTURES_SHARD_{sid}.log')
   for f in (d/'input').glob('*') if (d/'input').exists() else []:shutil.copy2(f,data/f.name)
   for n in ['COMMIT.txt','SOURCE_SHA256.txt','INPUT_SHA256.txt']:shutil.copy2(d/n,out/f'SHARD_{sid}_{n}')
   shardinfo.append({'shard':sid,'rows':s['unique_configurations'],'target_count':s['screen_target_count'],'target_dd50':s['screen_target_dd50_count']})
   if (d/'search_direct_m1.cpp').exists():shutil.copy2(d/'search_direct_m1.cpp',dest/'search_direct_m1.cpp')
 assert len(seen)==1000000 and len(allhash)==1000000 and len(inputs)==1 and len(sources)==1
 v=pd.concat(frames,ignore_index=True);assert not v[['id','case']].duplicated().any();v.to_csv(out/'M1_VALIDATION.csv',index=False)
 for f in data.glob('*_M1.csv.gz'):
  with gzip.open(f,'rb') as src,open(f.with_suffix(''),'wb') as dst:shutil.copyfileobj(src,dst)
 summary.update({'unique_configurations':1000000,'configuration_stream_size':1000000,'shard':'MERGED_5_DISJOINT_SHARDS','screen_target_count':total_targets,'screen_target_dd50_count':total_dd,'train_pass_count':traincount,'M1_candidates':int(v.id.nunique()),'execution_resolution':'ALL_1000000_DIRECT_M1','input_sha256':next(iter(inputs)),'engine_sha256':next(iter(sources)),'shards':shardinfo})
 (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2));(out/'SHARD_COVERAGE.json').write_text(json.dumps({'ids':len(seen),'unique_parameter_tuples':len(allhash),'same_input_hash':True,'same_engine_hash':True,'no_duplicate_ids_or_parameters':True,'shards':shardinfo},indent=2));(out/'COMMIT.txt').write_text((dirs[0]/'COMMIT.txt').read_text());(out/'SOURCE_SHA256.txt').write_text((dirs[0]/'SOURCE_SHA256.txt').read_text())
 print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
