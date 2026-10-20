from pathlib import Path
import pandas as pd,numpy as np,json
ROOT=Path(__file__).resolve().parent

def main():
    d=pd.read_csv(ROOT/'EVENT_LEDGER.csv');one=[];paired=[]
    for (split,family,horizon),g in d.groupby(['split','family','horizon_min']):
        base=g[(g.variant=='baseline_first_touch')&(g.status=='COMPLETE')&g.tape_ready]
        ids=set(base.event_id);bm=base.set_index('event_id')
        for variant,v in g.groupby('variant'):
            x=v[(v.status=='COMPLETE')&v.event_id.isin(ids)].sort_values(['entry_ms','event_id'])
            keep=[];last=-1
            for idx,r in x.iterrows():
                if r.entry_ms>last:keep.append(idx);last=r.exit_ms
            z=x.loc[keep];one.append(z)
            for mult in (1,1.5,2):
                key=f'net_R_{mult:g}x';b=bm.loc[z.event_id,key].to_numpy();c=z[key].to_numpy()
                paired.append({'split':split,'family':family,'horizon_min':horizon,'variant':variant,'cost_multiple':mult,
                               'matched_n':len(z),'baseline_same_zones_mean_R':float(np.mean(b)) if len(b) else None,
                               'challenger_same_zones_mean_R':float(np.mean(c)) if len(c) else None,
                               'mean_timing_delta_R':float(np.mean(c-b)) if len(c) else None,
                               'baseline_same_zones_win_pct':float(100*np.mean(b>0)) if len(b) else None,
                               'challenger_win_pct':float(100*np.mean(c>0)) if len(c) else None})
    pd.concat(one).to_csv(ROOT/'ONE_POSITION_LEDGER.csv',index=False)
    pd.DataFrame(paired).to_csv(ROOT/'MATCHED_ZONE_ABLATION.csv',index=False)
    x=d[d.status.eq('COMPLETE')]
    assert np.allclose(x.side*(x.exit_px-x.entry_px)/x.risk_usd_per_btc,x.gross_R)
    for mult in (1,1.5,2):assert np.allclose(x[f'net_R_{mult:g}x'],x.gross_R-mult*x.cost_R)
    assert (x.entry_ms>x.decision_ms).all() and (x.available_ms<=x.touch_ms).all()
    duplicates=int(d.duplicated(['event_id','variant','horizon_min']).sum());assert duplicates==0
    (ROOT/'LEDGER_RECONCILIATION.json').write_text(json.dumps({'completed_model_rows':len(x),
        'gross_and_net_R_cash_identity':'PASS','entry_after_decision':'PASS','zone_available_before_touch':'PASS',
        'duplicate_event_variant_horizon_rows':duplicates,
        'note':'Counterfactual variant/horizon rows are not independent trades and must not be summed as a combined portfolio.'},indent=2)+'\n')

if __name__=='__main__':main()
