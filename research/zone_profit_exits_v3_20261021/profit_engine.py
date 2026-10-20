from pathlib import Path
import sys,json,hashlib
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'baseline_v2'))
import challenger as v2
v2.ROOT=ROOT

def entry(e,decision,t,q):
    j=int(np.searchsorted(t,decision+1000))
    if j>=len(t) or not np.isfinite(q[j,0]):return None,'NO_ENTRY_QUOTE'
    s=e['side'];px=float(q[j,1 if s==1 else 0]);risk=s*(px-e['stop'])
    if not .15*e['atr']<=risk<=4*e['atr']:return None,'INVALID_RISK'
    cap=int(np.searchsorted(t,t[j]+7_200_000))
    primary=bool(cap<len(t) and np.isfinite(q[j:cap+1,:2]).all())
    return {'j':j,'entry_ms':int(t[j]),'entry_px':px,'risk_usd_per_btc':float(risk),
            'primary_eligible':primary,'primary_exclusion':None if primary else 'INCOMPLETE_OR_GAPPED120MIN_WINDOW'},'ENTRY_AVAILABLE'

def simulate(e,en,t,q,policy):
    j=en['j'];s=e['side'];ep=en['entry_px'];risk=en['risk_usd_per_btc'];stop=float(e['stop'])
    cap=int(np.searchsorted(t,t[j]+policy['hold_min']*60_000))
    if cap>=len(t):return {'status':'RIGHT_CENSORED'},[]
    rr=float(policy['tp_R']);structural=False
    destination=e.get('opposing_target_at_touch')
    if policy.get('structural_cap') and destination is not None and np.isfinite(destination):
        room=s*(destination-ep)/risk
        if room>0:rr=min(rr,float(room));structural=True
    target=ep+s*risk*rr;remaining=1.;legs=[];partial=False;peak=0.;protected=False
    active_stop=stop;reason=None
    for k in range(j,cap+1):
        px=float(q[k,0 if s==1 else 1])
        if not np.isfinite(px):return {'status':'QUOTE_GAP_CENSORED'},legs
        move=s*(px-ep)/risk
        peak=max(peak,move)
        if s*(px-active_stop)<=0:reason='STOP'
        elif s*(px-target)>=0:reason='TARGET'
        elif k==cap:reason='TIMEOUT'
        elif policy.get('protect_after_min') and not protected and t[k]-t[j]>=policy['protect_after_min']*60_000:
            protected=True
            if peak<policy['required_mfe_R']:reason='TIME_PROTECT'
        if reason:
            legs.append({'fraction':remaining,'exit_ms':int(t[k]),'exit_px':px,'reason':reason})
            remaining=0.;break
        if policy.get('partial_at_R') and not partial and move>=policy['partial_at_R']:
            w=float(policy['partial_fraction']);legs.append({'fraction':w,'exit_ms':int(t[k]),'exit_px':px,'reason':'PARTIAL'})
            remaining-=w;partial=True
        # Changes become effective on the NEXT quote, never retroactive to k.
        stop_in_R=s*(active_stop-ep)/risk
        if policy.get('be_after_R') and peak>=policy['be_after_R']:
            stop_in_R=max(stop_in_R,0.)
        if policy.get('trail_after_R') and peak>=policy['trail_after_R']:
            stop_in_R=max(stop_in_R,peak-policy['trail_distance_R'])
        active_stop=ep+s*risk*stop_in_R
    assert remaining==0 and abs(sum(x['fraction'] for x in legs)-1)<1e-12
    gross=sum(x['fraction']*s*(x['exit_px']-ep) for x in legs)
    exit_notional=sum(x['fraction']*x['exit_px'] for x in legs)
    weighted_seconds=sum(x['fraction']*(x['exit_ms']-t[j])/1000 for x in legs)
    cost=(ep+exit_notional)*.00065+ep*.0003*weighted_seconds/86400
    r={'status':'COMPLETE','entry_ms':int(t[j]),'exit_ms':max(x['exit_ms'] for x in legs),
       'entry_px':ep,'risk_usd_per_btc':risk,'original_stop':stop,'target_R':rr,'target_px':target,
       'structural_target_used':structural,'structural_fallback':bool(policy.get('structural_cap') and not structural),
       'gross_R':float(gross/risk),'cost_R':float(cost/risk),'gross_usd_per_initial_btc':float(gross),
       'cost_usd_per_initial_btc':float(cost),'reason':reason,'legs_n':len(legs),'weighted_duration_s':weighted_seconds}
    for c in [1,1.5,2]:r[f'net_R_{c:g}x']=float((gross-c*cost)/risk)
    return r,legs

def metrics(x,opportunities):
    rows=[]
    for c in [1,1.5,2]:
        p=x[f'net_R_{c:g}x'].to_numpy(float) if len(x) else np.array([])
        losses=-p[p<0].sum();equity=np.r_[0,np.cumsum(p)];dd=np.maximum.accumulate(equity)-equity
        rows.append({'cost_multiple':c,'n':len(p),'wins':int((p>0).sum()),'win_pct':100*(p>0).mean() if len(p) else None,
                     'sum_net_R':float(p.sum()),'mean_net_R':float(p.mean()) if len(p) else None,
                     'PF_R':float(p[p>0].sum()/losses) if losses>0 else None,
                     'max_cumulative_R_DD':float(dd.max()),'baseline_opportunities':opportunities,
                     'R_per_opportunity':float(p.sum()/opportunities) if opportunities else None})
    return rows

def summarize(d):
    rows=[];accepted=[]
    for split,g in d.groupby('split'):
        primary=g[g.primary_eligible & g.status.eq('COMPLETE')];n=primary.event_id.nunique()
        for pid,x in primary.groupby('policy'):
            x=x.sort_values(['entry_ms','event_id'])
            for scope in ['paired_events','one_position']:
                z=x
                if scope=='one_position':
                    ix=[];last=-1
                    for idx,r in x.iterrows():
                        if r.entry_ms>last:ix.append(idx);last=r.exit_ms
                    z=x.loc[ix];accepted.append(z)
                for m in metrics(z,n):rows.append({'split':split,'policy':pid,'scope':scope,**m})
    return pd.DataFrame(rows),pd.concat(accepted,ignore_index=True) if accepted else pd.DataFrame()

def run(days,out_prefix):
    cfg=json.loads((ROOT/'LOCKED_PROTOCOL_V3.json').read_text());rows=[];fills=[];signals=[];legacy=[]
    for day in days:
        raw,t,q,mid,bars=v2.load_day(day);events,_=v2.opportunities(day,raw,t,mid,bars);flow=v2.flow_arrays(day,t)
        for e in [e for e in events if e['family']=='H1_SD']:
            signal,why=v2.absorption(e,t,q,mid,flow)
            signal_row={**e,'signal_status':why,'decision_ms':signal['signal_ms'] if signal else None}
            if not signal:signals.append({**signal_row,'entry_status':'NO_SIGNAL'});continue
            en,status=entry(e,signal['signal_ms'],t,q);signals.append({**signal_row,'entry_status':status,**(en or {})})
            if en is None:continue
            split='training' if day in cfg['training_days'] else 'seen_diagnostic' if day in cfg['previously_seen_diagnostic_days'] else 'new_validation'
            old=v2.simulate(e,signal['signal_ms'],t,q,60);legacy.append({**e,**old})
            for policy in cfg['exit_variants']:
                result,legs=simulate(e,en,t,q,policy)
                rows.append({**e,**en,'decision_ms':signal['signal_ms'],'split':split,'policy':policy['id'],**result})
                for leg_n,leg in enumerate(legs):fills.append({'event_id':e['event_id'],'day':day,'policy':policy['id'],'leg_n':leg_n,
                    'entry_ms':en['entry_ms'],'entry_px':en['entry_px'],'side':e['side'],'risk_usd_per_btc':en['risk_usd_per_btc'],
                    'model_trade_status':result['status'],**leg})
        print(day,'H1 touches',sum(e['family']=='H1_SD' for e in events),'signals',len([x for x in signals if x['day']==day]),flush=True)
    df=pd.DataFrame(rows)
    for col in ['available_ms','touch_ms','decision_ms','entry_ms','exit_ms']:
        df[col.replace('_ms','_utc')]=pd.to_datetime(df[col],unit='ms',utc=True)
    df.to_csv(ROOT/f'{out_prefix}_EXIT_LEDGER.csv',index=False)
    pd.DataFrame(fills).to_csv(ROOT/f'{out_prefix}_FILL_LEDGER.csv',index=False)
    pd.DataFrame(signals).to_csv(ROOT/f'{out_prefix}_SIGNALS.csv',index=False)
    pd.DataFrame(legacy).to_csv(ROOT/f'{out_prefix}_LEGACY_CONTROL.csv',index=False)
    summary,one=summarize(df);summary.to_csv(ROOT/f'{out_prefix}_SUMMARY.csv',index=False)
    one.to_csv(ROOT/f'{out_prefix}_ONE_POSITION_LEDGER.csv',index=False)
    return summary,df

def select(summary):
    train=summary[(summary.split=='training') & summary.scope.eq('one_position')]
    rows=[]
    for policy,g in train.groupby('policy'):
        normal=g[g.cost_multiple==1].iloc[0];stress=g[g.cost_multiple==1.5].iloc[0]
        qualified=bool(normal.n>=5 and normal.mean_net_R>0 and stress.mean_net_R>0 and normal.PF_R>1 and stress.PF_R>1)
        rows.append({'policy':policy,'training_screen_pass':qualified,'n':int(normal.n),
                     'train_mean_R_1x':normal.mean_net_R,'train_mean_R_15x':stress.mean_net_R,
                     'rank_profit_per_opportunity_15x':stress.R_per_opportunity,'rank_DD_15x':stress.max_cumulative_R_DD})
    ranked=pd.DataFrame(rows).sort_values(['training_screen_pass','rank_profit_per_opportunity_15x','rank_DD_15x','policy'],ascending=[False,False,True,True])
    ranked.to_csv(ROOT/'TRAIN_SELECTION_RANKING.csv',index=False)
    best=ranked.iloc[0].to_dict();best.update({'selection_source':'Feb/Mar training only','new_validation_results_seen_at_selection':False,
                                            'not_live_qualified':True,'protocol_sha256':hashlib.sha256((ROOT/'LOCKED_PROTOCOL_V3.json').read_bytes()).hexdigest()})
    (ROOT/'LOCKED_TRAIN_SELECTION.json').write_text(json.dumps(best,indent=2)+'\n')
    print('TRAIN SELECTION',json.dumps(best),flush=True)
    return best

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['old','new']);a=parser.parse_args()
    c=json.loads((ROOT/'LOCKED_PROTOCOL_V3.json').read_text())
    if a.stage=='old':
        summary,_=run(c['training_days']+c['previously_seen_diagnostic_days'],'OLD');select(summary)
    else:
        assert (ROOT/'LOCKED_TRAIN_SELECTION.json').exists(),'Selection must be locked before new outcomes'
        run(c['new_validation_days'],'NEW')
