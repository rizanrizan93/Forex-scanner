from pathlib import Path
import json
import pandas as pd
root=Path(__file__).resolve().parent
d=pd.read_csv(root/'results/screen.csv')
keys=['base','sl','tp','hold','trend','session','risk','mask','direction']
rows=[]
for k,g in d.groupby(keys):
 train=g[g.year<=2022];ev=g[g.year.between(2023,2025)];partial=g[g.year==2026]
 hit=train[train.goal_minute>0]
 r={name:(v.item() if hasattr(v,"item") else v) for name,v in zip(keys,k)};r.update(dev_goals=int((train.goal_minute>0).sum()),dev_trials=len(train),dev_worst_balance=float(train.balance.min()),dev_max_dd_upper=float(train.dd_upper.max()),dev_median_days=float(hit.days_to_1000.median()) if len(hit) else None,eval_goals=int((ev.goal_minute>0).sum()),eval_trials=len(ev),eval_worst_balance=float(ev.balance.min()),eval_max_dd_upper=float(ev.dd_upper.max()),partial2026_goals=int((partial.goal_minute>0).sum()),partial2026_worst_balance=float(partial.balance.min()),all_trades=int(g.trades.sum()),gap_trades=int(g.gap_trades.sum()))
 r['score']=r['dev_goals']*1000000+r['dev_worst_balance']*100-r['dev_max_dd_upper']*10000-(r['dev_median_days'] or 366)
 rows.append(r)
rows.sort(key=lambda r:r['score'],reverse=True)
short=[]
for mask in [1,4,5]:
 a=[r for r in rows if r['mask']==mask];short+=a[:3]
out=dict(unique_configurations=len(rows),actual_annual_screens=len(d),all_development_goals=sum(r['dev_goals']==8 for r in rows),all_16_goals=sum(r['dev_goals']==8 and r['eval_goals']==6 and r['partial2026_goals']==2 for r in rows),selection_uses_development_only=True,standalone_module_only=True,shortlist=short,top=rows[:20])
(root/'results/screen_summary.json').write_text(json.dumps(out,indent=2))
print(json.dumps(out,indent=2))
