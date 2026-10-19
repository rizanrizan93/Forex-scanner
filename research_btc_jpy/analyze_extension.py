import sys,pathlib,json
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
root=pathlib.Path(sys.argv[1]);symbol=sys.argv[2];r=root/f'results_{symbol}';e=root/'extension';v=pd.read_csv(e/'LOCKED_EXTENSION_RESULTS.csv');leaders=json.loads((r/'MARCH_LEADERS.json').read_text());checks=[];maxerror=0
for p in sorted(e.glob('candidate_*_extended_ledger.csv')):
 cid=int(p.name.split('_')[1]);q=pd.read_csv(p)
 if q.empty:continue
 expected=q.side*(q.exit_price-q.entry_average)*q.quantity
 if symbol=='USDJPY':expected=expected/q.exit_price
 expected=expected-q.entry_commission-q.exit_commission-q.financing
 b=v[(v.id==cid)&(v['case']=='EXTENDED_BASE')].iloc[0]
 err=max(float(np.abs(expected-q.net_pnl).max()),float(np.abs(100+q.net_pnl.cumsum()-q.balance).max()),abs(float(q.balance.iloc[-1])-float(b.equity)));maxerror=max(maxerror,err)
 assert err<max(1e-6,abs(b.equity)*1e-9),f'cash_mismatch_{cid}'
 entry=pd.to_datetime(q.entry_utc,utc=True);exit=pd.to_datetime(q.exit_utc,utc=True);assert (exit>=entry).all() and len(q)==int(b.trades)
 q['month']=exit.dt.strftime('%Y-%m');q['year']=exit.dt.year
 for key in ['month','year']:
  z=q.groupby(key).agg(net_profit=('net_pnl','sum'),trades=('net_pnl','size'),wins=('net_pnl',lambda x:int((x>0).sum())),adds=('adds','sum'))
  if key=='month':z=z.reindex(pd.period_range('2019-01','2026-10',freq='M').astype(str),fill_value=0)
  z['ending_balance']=100+z.net_profit.cumsum();z.to_csv(e/f'candidate_{cid}_extended_{key}.csv')
 checks.append({'id':cid,'cash_error':err,'trades':len(q),'win_rate':100*(q.net_pnl>0).mean(),'months':94,'October_partial_through_day':15})
 if cid in leaders.values():
  c=pd.read_csv(e/f'candidate_{cid}_extended_equity.csv');c['timestamp']=pd.to_datetime(c.timestamp,utc=True);fig,ax=plt.subplots(2,1,figsize=(12,7),sharex=True,gridspec_kw={'height_ratios':[2,1]});ax[0].plot(c.timestamp,c.equity,lw=.7);ax[0].set_yscale('symlog',linthresh=10);ax[0].set_ylabel('Equity USD');ax[0].set_title(f'{symbol} locked March candidate {cid} through15Oct2026 (M1 model)');ax[0].axvline(pd.Timestamp('2026-04-01',tz='UTC'),ls='--',lw=.8,color='gray');ax[1].plot(c.timestamp,-c.drawdown_pct,color='darkred',lw=.7);ax[1].set_ylabel('Drawdown %');ax[0].grid(alpha=.2);ax[1].grid(alpha=.2);fig.tight_layout();fig.savefig(e/f'candidate_{cid}_extended_equity_drawdown.png',dpi=130);plt.close(fig)
base=v[v['case']=='EXTENDED_BASE'];proof=json.loads((e/'LOCKED_PARAMETER_PROOF.json').read_text());assert proof['all_March_results_reconciled'] and len(base)==proof['parameters'];assert set(base.id)==set(pd.read_csv(r/'LOCKED_SELECTION.csv').id)
summary={'symbol':symbol,'parameters_locked_using_March_only':len(base),'ending_period':'2026-10-15 23:59:00 UTC','target100k_among_locked_cohort':int((base.equity>=100000).sum()),'target100k_DD50_among_locked_cohort':int(((base.equity>=100000)&(base.floating_dd<50)).sum()),'max_cash_error':maxerror,'ledger_checks':checks,'march_leaders':leaders,'not_selected_on_extension_results':True}
(e/'EXTENSION_RECONCILIATION.json').write_text(json.dumps(summary,indent=2));print(summary)
