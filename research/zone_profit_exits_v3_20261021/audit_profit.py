from pathlib import Path
import json,hashlib
import numpy as np,pandas as pd
from profit_engine import summarize,ROOT

def main():
    lock=json.loads((ROOT/'SELECTION_LOCK_PROOF.json').read_text())
    assert hashlib.sha256((ROOT/'LOCKED_TRAIN_SELECTION.json').read_bytes()).hexdigest()==lock['selection_sha256']
    ledger=pd.concat([pd.read_csv(ROOT/f'{part}_EXIT_LEDGER.csv') for part in ['OLD','NEW']],ignore_index=True)
    fills=pd.concat([pd.read_csv(ROOT/f'{part}_FILL_LEDGER.csv') for part in ['OLD','NEW']],ignore_index=True)
    summary,one=summarize(ledger)
    summary.to_csv(ROOT/'COMPARISON.csv',index=False);one.to_csv(ROOT/'ONE_POSITION_LEDGER.csv',index=False)
    ledger.to_csv(ROOT/'EXIT_LEDGER.csv',index=False);fills.to_csv(ROOT/'FILL_LEDGER.csv',index=False)
    complete=ledger[ledger.status.eq('COMPLETE')];max_residual=0.
    for r in complete.itertuples():
        f=fills[(fills.event_id==r.event_id)&(fills.policy==r.policy)]
        assert abs(f.fraction.sum()-1)<1e-12
        gross=float((f.fraction*r.side*(f.exit_px-r.entry_px)).sum())
        duration=float((f.fraction*(f.exit_ms-r.entry_ms)/1000).sum())
        cost=(r.entry_px+(f.fraction*f.exit_px).sum())*.00065+r.entry_px*.0003*duration/86400
        max_residual=max(max_residual,abs(gross-r.gross_usd_per_initial_btc),abs(cost-r.cost_usd_per_initial_btc))
    assert max_residual<1e-8
    for c in [1,1.5,2]:assert np.allclose(complete[f'net_R_{c:g}x'],complete.gross_R-c*complete.cost_R,atol=1e-10)
    assert (complete.entry_ms>complete.decision_ms).all() and (complete.available_ms<=complete.touch_ms).all()
    assert ledger.duplicated(['event_id','policy']).sum()==0
    paired=[]
    for split,g in ledger.groupby('split'):
        g=g[g.primary_eligible & g.status.eq('COMPLETE')]
        base=g[g.policy.eq('BASE_1R_60')].set_index('event_id')
        for policy,x in g.groupby('policy'):
            for c in [1,1.5,2]:
                a=base.loc[x.event_id,f'net_R_{c:g}x'].to_numpy();b=x[f'net_R_{c:g}x'].to_numpy();delta=b-a
                paired.append({'split':split,'policy':policy,'cost_multiple':c,'matched_events':len(x),
                               'base_same_entries_mean_R':a.mean() if len(a) else None,
                               'challenger_mean_R':b.mean() if len(b) else None,
                               'mean_exit_delta_R':delta.mean() if len(delta) else None,
                               'sum_exit_delta_R':delta.sum(),'improved_events':int((delta>1e-10).sum()),
                               'worse_events':int((delta< -1e-10).sum())})
    pd.DataFrame(paired).to_csv(ROOT/'MATCHED_ENTRY_EXIT_ABLATION.csv',index=False)
    daily=[]
    for (day,policy),g in one.groupby(['day','policy']):
        daily.append({'day':day,'policy':policy,'split':g.split.iloc[0],'n':len(g),
                      **{f'sum_net_R_{c:g}x':float(g[f'net_R_{c:g}x'].sum()) for c in [1,1.5,2]}})
    pd.DataFrame(daily).to_csv(ROOT/'DAILY.csv',index=False)
    directions=[]
    for (split,policy,side),g in one.groupby(['split','policy','side']):
        directions.append({'split':split,'policy':policy,'direction':'BUY' if side==1 else 'SELL','n':len(g),
                           **{f'sum_net_R_{c:g}x':float(g[f'net_R_{c:g}x'].sum()) for c in [1,1.5,2]}})
    pd.DataFrame(directions).to_csv(ROOT/'DIRECTION_CONTRIBUTIONS.csv',index=False)
    counts=ledger[['event_id','day','split','primary_eligible','primary_exclusion']].drop_duplicates('event_id')
    counts.to_csv(ROOT/'COHORT_AVAILABILITY.csv',index=False)
    structural=complete[complete.policy.eq('STRUCT_CAP2_120')].copy()
    structural['binding_cap']=structural.target_R<2-1e-10
    audit={'complete_exit_model_rows':len(complete),'all_signal_exit_model_rows':len(ledger),
           'status_counts':ledger.status.value_counts().to_dict(),'signal_events_with_valid_entry':counts.groupby('split').size().to_dict(),
           'common120m_events':counts[counts.primary_eligible].groupby('split').size().to_dict(),
           'max_cash_identity_residual_usd_per_initial_btc':max_residual,'cost_identity':'PASS',
           'causal_entry_and_zone_times':'PASS','selection_hash_unchanged':True,
           'structural_target_usage':structural.groupby('split').structural_target_used.agg(['count','sum']).to_dict(),
           'structural_binding_events':structural.groupby('split').binding_cap.sum().to_dict(),
           'structural_flag_semantics':'target_used means a valid forward boundary was observed; binding_events counts cases where it actually reduced the2R cap',
           'no_portfolio_compounding_claim':True,'no_live_actions':True}
    (ROOT/'RESULT_AUDIT.json').write_text(json.dumps(audit,indent=2)+'\n')
    print(json.dumps(audit,indent=2),flush=True)

if __name__=='__main__':main()
