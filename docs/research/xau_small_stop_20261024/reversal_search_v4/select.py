from pathlib import Path
import pandas as pd,numpy as np,json
P=Path('reversal_search_v4')
s=pd.read_csv(P/'search_results.csv');fams={v:k for k,v in json.loads((P/'families.json').read_text()).items()};profiles=json.loads((Path('reversal_search_v3/profiles_phase2.json')).read_text());s['name']=s.family.map(fams);s['profile_name']=s.profile.astype(str).map(profiles)
for p in ['train','review','q1','all']:
 s[p+'_pf']=s[p+'_pos']/s[p+'_neg'].replace(0,np.nan);s[p+'_win_pct']=100*s[p+'_win']/s[p+'_n'].replace(0,np.nan);s[p+'_tp_pct']=100*s[p+'_tp']/s[p+'_n'].replace(0,np.nan);s[p+'_mean_risk']=s[p+'_risk']/s[p+'_n'].replace(0,np.nan)
s['censor_pct']=100*s.censored/(s.censored+s.all_n).replace(0,np.nan)
keys=['family','frac','buffer','target','profile','ttl','session','hold','direction']
normal=s[s.cost==1].copy();stress=s[s.cost==2].copy();cols=['review_pf','review_n','review_win_pct','review_tp_pct','all_pf','censor_pct']
normal=normal.merge(stress[keys+cols],on=keys,suffixes=('','_cost2'))
normal['train_pass']=(normal.train_n>=60)&(normal.train_win_pct>=55)&(normal.train_tp_pct>=50)&(normal.train_pf>=1.5)
normal['review_pass']=(normal.review_n>=30)&(normal.review_win_pct>=55)&(normal.review_tp_pct>=50)&(normal.review_pf>=1.5)&(normal.review_pf_cost2>=1.2)&(normal.censor_pct<=2)&(normal.censor_pct_cost2<=2)
normal['both_pass']=normal.train_pass&normal.review_pass
normal.to_csv(P/'phase3_fixed_combined_results.csv',index=False)
selected=[]
for target,g in normal.groupby(['target','direction']):
 eligible=g[g.train_pass].sort_values(['train_pf','train_n'],ascending=False)
 if len(eligible):selected.append(eligible.iloc[0])
primary=pd.DataFrame(selected);primary.to_csv(P/'phase3_fixed_train_primary.csv',index=False)
passing=normal[normal.both_pass].sort_values(['review_pf','review_n'],ascending=False);passing.to_csv(P/'phase3_fixed_posthoc_numeric_pass.csv',index=False)
short=normal[normal.train_pass].sort_values(['train_pf','train_n'],ascending=False).head(100);short.to_csv(P/'phase3_fixed_train_top100.csv',index=False)
closest=normal[(normal.train_n>=60)&(normal.review_n>=30)&(normal.censor_pct<=2)&(normal.censor_pct_cost2<=2)].copy();closest['score']=np.minimum(closest.train_tp_pct,closest.review_tp_pct)*np.minimum(closest.train_pf,closest.review_pf);closest=closest.sort_values('score',ascending=False);closest.head(100).to_csv(P/'phase3_fixed_closest_posthoc100.csv',index=False)
display=['direction','name','target','frac','buffer','profile_name','ttl','session','hold','train_n','train_tp_pct','train_pf','review_n','review_tp_pct','review_pf','review_pf_cost2','all_n','all_mean_risk','both_pass']
print('CONFIGS',len(s),'TRAIN PASS',int(normal.train_pass.sum()),'BOTH PASS',len(passing))
print('PRIMARY\n',primary[display].to_string(index=False) if len(primary) else 'NONE')
print('NUMERIC PASS\n',passing[display].head(15).to_string(index=False))
print('CLOSEST\n',closest[display].head(8).to_string(index=False))
info={'configs':len(s),'train_pass':int(normal.train_pass.sum()),'numeric_both_pass':len(passing),'primary':json.loads(primary.to_json(orient='records')),'status':'Exploratory. Numeric pass is not prospective validation.'};(P/'phase3_fixed_selection_summary.json').write_text(json.dumps(info,indent=2))
