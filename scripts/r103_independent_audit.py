"""RIZAN R10.3 independent integrity audit of fixed R10.2 setup.
Research-only; no live orders, no edits to production. Archive input run 44901264975.
Evaluate fixed frozen settings; never reselect thresholds using 2024-26.
"""
import argparse,json, hashlib
from pathlib import Path
import numpy as np,pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss
from r102_calibrated import prepare,platt,metrics,context
from r10_million import load,ohlc_indicators,wilson
OUT=Path('artifacts');OUT.mkdir(exist_ok=True)
EXPECTED={'1h':{'buy':.677954,'sell':.620780,'cut':.58},
          '4h':{'buy':.817694,'sell':.770801,'cut':.68}}
def report(tf):
    d,z,x,y,valid=prepare(tf);h=1 if tf=='1h' else 4;years=z.index.year
    tr=valid&(years>=2019)&(years<=2022)
    cal=valid&(years==2023)&(z.index.month<=6)
    va=valid&(years==2023)&(z.index.month>=7)
    te=valid&(years>=2024)&(years<=2026)
    assert min(int(tr.sum()),int(cal.sum()),int(va.sum()),int(te.sum()))>100
    data=x.to_numpy(dtype=np.float32)
    model=HistGradientBoostingClassifier(max_iter=120,max_depth=5,
        max_leaf_nodes=31,l2_regularization=1,learning_rate=.05,random_state=42)
    model.fit(data[tr],y[tr])
    raw_cal=model.predict_proba(data[cal])[:,1]
    raw_val=model.predict_proba(data[va])[:,1];raw_test=model.predict_proba(data[te])[:,1]
    pval=platt(raw_cal,y[cal],raw_val)
    ptest=platt(raw_cal,y[cal],raw_test)
    cut=EXPECTED[tf]['cut']
    ret=(d.c.shift(-1)-d.c).to_numpy()
    current=metrics(y[te],ptest,cut,ret[te],cost=.7)
    valuation=metrics(y[va],pval,cut,ret[va],cost=.7)
    unchanged=all(abs(current[direction]['accuracy']-EXPECTED[tf][direction])<.000002 for direction in ['buy','sell'])
    # Independent, executable proxy: trade at NEXT bar open, exit at that bar close.
    nex=(d.c.shift(-1)-d.o.shift(-1)).to_numpy()
    execution=metrics((nex[te]>0).astype('int8'),ptest,cut,nex[te],cost=.7)
    baseline={'mean_buy_direction':float(y[te].mean()),
        'persistence_accuracy':float(np.mean((d.c.to_numpy()[te]-d.o.to_numpy()[te]>0)==y[te])),
        'always_buy_accuracy':float(y[te].mean()),
        'always_sell_accuracy':float(1-y[te].mean()),
        'brier_raw':float(brier_score_loss(y[te],raw_test)),
        'brier_platt':float(brier_score_loss(y[te],ptest))}
    # Null hypothesis: randomized training targets should not predict outcome.
    rng=np.random.default_rng(812)
    shuffle_y=np.array(y[tr],copy=True);rng.shuffle(shuffle_y)
    negative=HistGradientBoostingClassifier(max_iter=120,max_depth=5,
        max_leaf_nodes=31,l2_regularization=1,learning_rate=.05,random_state=42)
    negative.fit(data[tr],shuffle_y)
    null_p=negative.predict_proba(data[te])[:,1]
    baseline['shuffle_label_model_accuracy']=float(np.mean((null_p>=.5)==y[te]))
    baseline['shuffle_label_model_brier']=float(brier_score_loss(y[te],null_p))
    # Temporal causality: recreate selected feature vectors with only information available
    # through the decision candle end, and compare to full-history feature values.
    full_h1=load('1h')
    samples=[]
    times=np.flatnonzero(valid & (years>=2023)&(z.index.month.isin([2,5,9,11])))
    locs=times[np.linspace(0,len(times)-1,min(12,len(times)),dtype=int)]
    for i in locs:
        stamp=z.index[i];bar_end=stamp+pd.Timedelta(hours=h)
        hist_d=d.loc[d.index<=stamp]
        hist_h1=full_h1.loc[full_h1.index<bar_end]
        prefix=ohlc_indicators(hist_d)
        context(prefix,hist_h1,h)
        b=prefix.loc[stamp];a=z.loc[stamp]
        both=[k for k in a.index if k in b.index]
        delta=[]
        for k in both:
            av,bv=a[k],b[k]
            if pd.isna(av) and pd.isna(bv):continue
            if not np.isclose(av,bv,atol=1e-9,rtol=1e-9,equal_nan=True):
                delta.append({'feature':k,'full':str(av),'prefix':str(bv)})
        samples.append({'timestamp':str(stamp),'differences':delta[:5],'total_differences':len(delta)})
    prefix_pass=all(s['total_differences']==0 for s in samples)
    # Missing intraweek bars and periods: full source may have failed fetch segments.
    dt=d.index.to_series().diff().dropna()
    expected= pd.Timedelta(hours=h)
    shortgaps=int(((dt>expected)&(dt<=pd.Timedelta(days=3))).sum())
    longgaps=int((dt>pd.Timedelta(days=3)).sum())
    # Monthly eval performance and blocked uncertainty.
    monthvals=[]
    test_dates=z.index[te]
    for month in sorted(set(test_dates.to_period('M').astype(str))):
        sel=(test_dates.to_period('M').astype(str)==month)
        if not sel.any():continue
        monthvals.append({'month':month,**metrics(y[te][sel],ptest[sel],cut,ret[te][sel],cost=.7)})
    peryear=[]
    for year in [2024,2025,2026]:
        sel=te&(years==year)
        if not sel.any():continue
        idx=years[te]==year
        peryear.append({'year':year,**metrics(y[sel],ptest[idx],cut,ret[sel],cost=.7)})
    g=np.abs((d.o.shift(-1)-d.c).to_numpy()[te])
    gap={'next_open_minus_current_close_abs_avg':float(np.nanmean(g)),
         'p95':float(np.nanpercentile(g,95)), 'p99':float(np.nanpercentile(g,99))}
    result={'version':'R10.3','tf':tf,'fixed_setup':{'model':'HistGradientBoostingClassifier max_depth=5 leaves=31 l2=1 max_iter=120 learning_rate=.05','cut':cut,'calibration':'Platt calibrated on 2023H1'},
      'data_sources':'GitHub R10 archived historical bars run 44901264975',
      'counts':{'train':int(tr.sum()),'cal':int(cal.sum()),'val':int(va.sum()),'evaluation':int(te.sum()),'total_bars':len(d)},
      'old_leaked_R102_metrics_reproduced_after_fix':unchanged,
      'validation':valuation,'evaluation':current,'entry_next_bar_open_exit_next_bar_close_cost_scenario':execution,
      'baseline':baseline,'prefix_causality_test':{'pass':prefix_pass,'samples':samples},
      'source_quality':{'first':str(d.index.min()),'last':str(d.index.max()),'same_session_missing_bars_or_shortgaps':shortgaps,'long_gaps':longgaps,'open_gap':gap},
      'annual_evaluation':peryear,'monthly_evaluation':monthvals,
      'recommendation':'RESEARCH ONLY / DO NOT PROMOTE TO LIVE',
      'known_issues':['2024-26 evaluation is not untouched due prior repeated tests',
        'calibration chosen after previous research; data snooping risk',
        '0.7 USD/oz friction is only a scenario; not broker bid/ask/spread/slippage',
        'OHLC volume pressure is proxy only; no actual order flow',
        'W1 grouping uses calendar Monday period and includes Sunday open hour; broker calendar needs validation',
        'No macro point-in-time fields currently used',
        'Accuracy close-to-close not equal execution under spread, latency, swaps']}
    OUT.joinpath(f'r103-audit-{tf}.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({'stage':'audit_finished','tf':tf,'old_leaked_metrics_still_present':unchanged,'prefix_pass':prefix_pass,
        'evaluation':current,'entry_next_open':execution,'baseline':baseline,
        'gaps':result['source_quality']}),flush=True)
    if not prefix_pass:raise AssertionError('LOOKAHEAD PREFIX INVARIANCE FAILED')
    if unchanged:raise AssertionError('OLD LEAKED PERFORMANCE UNCHANGED: investigate fix efficacy')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--tf',choices=['1h','4h'],required=True)
    report(p.parse_args().tf)
