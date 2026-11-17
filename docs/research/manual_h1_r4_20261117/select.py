"""Freeze training/validation selection without reading 2025 results."""
from pathlib import Path
import sys,json,hashlib
import pandas as pd
P=Path(sys.argv[1]);v=pd.read_csv(P/'results/validation.csv');s=pd.read_csv(P/'results/shortlist.csv');rank=[]
for c in s.itertuples():
    x=v[(v['style']==c.style)&(v.g==c.g)&(v.f==c.f)]
    def get(block,cost=1):return x[(x.block==block)&(x.cost==cost)].iloc[0]
    tr=get('train_2019_22');va=get('validation_2023_24');stress=get('validation_2023_24',1.5);allst=get('all_2019_24',1.5)
    annual=x[(x.block.isin([str(y) for y in range(2019,2025)]))&(x.cost==1)]
    passed=bool(tr.n>=150 and va.n>=80 and tr.pf>=1.1 and va.pf>=1.1 and stress.pf>=1 and (annual.sum_r>0).sum()>=4)
    rank.append(dict(style=c.style,g=c.g,f=c.f,admitted=passed,rank_score=min(tr.score,va.score,stress.mean_r,allst.mean_r),train_pf=tr.pf,validation_pf=va.pf,stress_validation_pf=stress.pf,positive_years=int((annual.sum_r>0).sum()),train_n=int(tr.n),validation_n=int(va.n)))
r=pd.DataFrame(rank).sort_values(['admitted','rank_score','style','g','f'],ascending=[False,False,True,True,True]);r.to_csv(P/'results/ranking.csv',index=False)
chosen=r[r.admitted].head(3)
status='EXPLORATORY_CANDIDATE' if len(chosen) else 'DIAGNOSTIC_ONLY_ADMISSION_FAILED'
if chosen.empty:chosen=r.head(1)
chosen[['style','g','f']].to_csv(P/'results/frozen.csv',index=False)
proof={'status':status,'chosen':chosen.to_dict('records'),'read_2025_results':False,'shortlist_sha256':hashlib.sha256((P/'results/shortlist.csv').read_bytes()).hexdigest(),'validation_sha256':hashlib.sha256((P/'results/validation.csv').read_bytes()).hexdigest()}
(P/'results/frozen.json').write_text(json.dumps(proof,indent=2));print(r.head(8).to_string(index=False));print(status)
