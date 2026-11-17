"""Package compact selected traces and two explicitly illustrative real charts."""
import argparse,gzip,hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
from research.zone_rebound.fixed10 import MIN,SCENARIOS,mask,select_indices,metric


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--xau',type=Path,required=True);p.add_argument('--eur',type=Path,required=True);p.add_argument('--fred',type=Path,required=True);a=p.parse_args();a.evidence.mkdir(parents=True,exist_ok=True)
    summary=json.loads((a.out/'summary.json').read_text());tr=pd.read_csv(a.out/'selected_ledger.csv.gz');e=pd.read_csv(a.out/'all_events.csv.gz');rank=pd.read_csv(a.out/'ranking.csv.gz')
    families=[]
    for family in sorted(e.family.unique()):
        if family.startswith('BASELINE_'):continue
        for side in (1,-1):
            r=rank[(rank.family==family)&(rank.side==side)&(rank.scenario=='H240_A10')]
            if not len(r):continue
            rule=r.iloc[0].to_dict();q=e[(e.family==family)&(e.side==side)&(e.tf==rule['tf'])].reset_index(drop=True)
            ids=select_indices(q,mask(q,rule['regime'],rule['phase'],rule['macro']));ids=ids[q.year.to_numpy()[ids]==2025]
            families.append(dict(rule=rule,test2025=metric(q,ids,'H240_A10')))
    (a.evidence/'structural_families.json').write_text(json.dumps(families,indent=2))
    model_ids=[f"{x['rule']['side']}_{x['rule']['scenario']}_{x['ablation']}" for x in summary['selected']]
    # Use 60 bits to retain all model memberships without duplicating events.
    keys=['family','tf','side','time_ns','pub_ns','reference']
    membership={}
    for row in tr.itertuples(index=False):
        k=tuple(getattr(row,c) for c in keys);membership[k]=membership.get(k,0)|(1<<model_ids.index(row.model_id))
    unique=tr.drop_duplicates(keys).copy();unique['model_mask_hex']=[hex(membership[tuple(x)]) for x in unique[keys].itertuples(index=False,name=None)]
    cols=['family','tf','side','year','time_ns','pub_ns','origin_ns','lo','hi','reference','age_hours','atr_h1','adx','slope','stretch','phase','eur15','eur60','real5','nom2_5','nom10_5','broad5','spread','complete_60','complete_240','target_minutes','mae_before_target','mfe_240','mae_240','model_mask_hex']
    cols += [c for sc in SCENARIOS for c in (sc,sc+'_timeout',sc+'_spread')]
    for year,q in unique.groupby('year'):
        z=q[cols].copy()
        for c in ('time_ns','pub_ns','origin_ns'):z[c.replace('_ns','_epoch_min')]=z.pop(c)//MIN
        for c in z.select_dtypes(include='bool').columns:z[c]=z[c].astype('int8')
        z.to_csv(a.evidence/f'selected_{int(year)}.csv.gz',index=False,compression='gzip',float_format='%.12g')
    (a.evidence/'models.json').write_text(json.dumps(dict(model_ids_bit_order=model_ids,unique_selected_events=len(unique),selected_memberships=len(tr),grid_rules=len(e.groupby(['family','tf','side']))*10*4*8,grid_rule_scenarios=len(e.groupby(['family','tf','side']))*10*4*8*6),indent=2))
    for name in ('summary.json','verification.json','ranking.csv.gz'):
        raw=(a.out/name).read_bytes()
        (a.evidence/(name if name.endswith('.gz') else name+'.gz')).write_bytes(raw if name.endswith('.gz') else gzip.compress(raw,mtime=0))
    # Archive exact downloaded vintage, including its source dates after replay end.
    (a.evidence/'fred_macro_snapshot.csv.gz').write_bytes(gzip.compress(a.fred.read_bytes(),mtime=0))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as md
    d=pd.read_csv(a.xau,usecols=['timestamp','open','high','low','close']);d.index=pd.to_datetime(d.pop('timestamp'),utc=True)
    eur=pd.read_csv(a.eur,usecols=['timestamp','close']);eur.index=pd.to_datetime(eur.pop('timestamp'),utc=True)+pd.Timedelta(minutes=1)
    examples=[]
    candidates=tr[(tr.model_id=='1_H240_A10_COMBINED')&(tr.year==2025)&tr.complete_240].sort_values('time_ns')
    for status in (True,False):
        row=candidates[candidates.H240_A10==status].iloc[0];at=pd.Timestamp(int(row.time_ns),tz='UTC');pub=pd.Timestamp(int(row.pub_ns),tz='UTC')
        start=min(pub-pd.Timedelta(minutes=60),at-pd.Timedelta(minutes=60));end=at+pd.Timedelta(minutes=240)
        q=d.loc[start:end].tz_convert('Asia/Jakarta');u=eur.loc[start:end].tz_convert('Asia/Jakarta')
        fig,(ax,bx)=plt.subplots(2,1,figsize=(12,6.5),sharex=True,gridspec_kw={'height_ratios':[3,1]},layout='constrained')
        ax.plot(q.index,q.close,color='#18354a',lw=1,label='XAU M1 close (bid)')
        ax.fill_between(q.index,q.low,q.high,color='#9db5c3',alpha=.25)
        ax.fill_between(q.index,row.lo,row.hi,where=q.index>=pub.tz_convert('Asia/Jakarta'),color='#18a57a',alpha=.22,label='FVG M15, frozen at publication')
        for y,color,label in [(row.reference,'#a26a00','Area entry reference'),(row.reference+10,'#16875c','Target +$10'),(row.reference-10,'#cf4141','Adverse -$10')]:ax.axhline(y,color=color,ls='--',lw=1,label=label)
        for dt,label in [(pub,'Published'),(at,'First return')]:
            dt=dt.tz_convert('Asia/Jakarta');ax.axvline(dt,color='#626262',ls=':',lw=1);ax.text(dt,ax.get_ylim()[1],label,ha='left',va='top',fontsize=8)
        text='Target before -$10' if status else 'Failed target-before-adverse/time rule'
        ax.set_title(f'Historical illustration — {text} | {at.tz_convert("Asia/Jakarta"):%d %b %Y %H:%M} WIB',loc='left',fontsize=12)
        ax.set_ylabel('XAUUSD ($/oz)');ax.legend(fontsize=8,ncol=2,loc='lower left');ax.grid(alpha=.15)
        bx.plot(u.index,u.close,color='#4666ad',lw=1);bx.set_ylabel('EURUSD\nUSD proxy');bx.ticklabel_format(useOffset=False,axis='y');bx.grid(alpha=.15)
        bx.xaxis.set_major_formatter(md.DateFormatter('%H:%M',tz=q.index.tz))
        bx.set_xlabel(f'WIB | EUR15 signed return at touch {row.eur15:.2f} bps; lagged real-yield 5-observation support {row.real5:.3f} pp\nTwo chosen examples explain mechanics; the complete selected sample determines the result.')
        filename='example_success.png' if status else 'example_failure.png';fig.savefig(a.evidence/filename,dpi=150);plt.close(fig)
        examples.append(dict(file=filename,time_wib=str(at.tz_convert('Asia/Jakarta')),reference=float(row.reference),lo=float(row.lo),hi=float(row.hi),success=bool(status)))
    (a.evidence/'examples.json').write_text(json.dumps(examples,indent=2))
    manifest={p.name:dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(a.evidence.iterdir()) if p.is_file() and p.name!='manifest.json'}
    (a.evidence/'manifest.json').write_text(json.dumps(manifest,indent=2));print(json.dumps(dict(unique_selected_events=len(unique),selected_memberships=len(tr),files={k:v['bytes'] for k,v in manifest.items()}),indent=2))

if __name__=='__main__':main()
