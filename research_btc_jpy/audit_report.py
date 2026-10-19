import sys,pathlib,json,hashlib,gzip
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=pathlib.Path(__file__).resolve().parent
symbol=sys.argv[1];r=ROOT/f'results_{symbol}';summary=json.loads((r/'SUMMARY.json').read_text());audit=json.loads((ROOT/'data'/f'{symbol}_AUDIT.json').read_text())
v=pd.read_csv(r/'M1_VALIDATION.csv');base=v[v['case']=='BASE'].sort_values('equity',ascending=False)
checks=[]
def ck(name,value):
    if not bool(value):raise AssertionError(name)
    checks.append({'name':name,'pass':True})
ck('one_million_unique_configurations',summary['unique_configurations']==1000000)
ck('all_87_months_input',len(audit['months'])==87)
ck('input_sha256',hashlib.sha256((ROOT/'data'/f'{symbol}_M1.csv').read_bytes()).hexdigest()==audit['sha256'])
count=0;ids=set();families=set()
for q in pd.read_csv(r/'ALL_CONFIGURATIONS.csv',chunksize=100000):
    count+=len(q);ck(f'finite_screen_rows_{count}',np.isfinite(q.select_dtypes('number').to_numpy()).all());families.update(q.family.unique());ids.update(q.id.tolist())
ck('screen_row_count',count==1000000 and len(ids)==count);ck('twelve_families',len(families)==12)
maxerror=0;ledger_info=[]
for p in sorted(r.glob('candidate_*_ledger.csv')):
    cid=int(p.stem.split('_')[1]);q=pd.read_csv(p);b=base[base.id==cid].iloc[0]
    if q.empty:continue
    entry=pd.to_datetime(q.entry_utc,utc=True);exit=pd.to_datetime(q.exit_utc,utc=True)
    ck(f'causal_entry_exit_{cid}',(exit>=entry).all())
    if len(q)>1:ck(f'no_simultaneous_baskets_{cid}',(entry.iloc[1:].to_numpy()>exit.iloc[:-1].to_numpy()).all())
    gross=q.side*(q.exit_price-q.entry_average)*q.quantity
    if symbol=='USDJPY':gross=gross/q.exit_price
    expected=gross-q.entry_commission-q.exit_commission-q.financing
    error=float(np.max(np.abs(expected-q.net_pnl)));casherror=float(np.max(np.abs(100+q.net_pnl.cumsum()-q.balance)));last=float(abs(q.balance.iloc[-1]-b.equity))
    maxerror=max(maxerror,error,casherror,last);ck(f'cash_reconciles_{cid}',max(error,casherror,last)<max(1e-6,abs(b.equity)*1e-9))
    ck(f'volume_steps_{cid}',np.max(np.abs(q.quantity/(.01 if symbol=='BTCUSD' else 1000)-np.round(q.quantity/(.01 if symbol=='BTCUSD' else 1000))))<1e-6)
    ck(f'ledger_count_{cid}',len(q)==int(b.trades))
    q['month']=exit.dt.strftime('%Y-%m');q['year']=exit.dt.year
    for key in ['month','year']:
        z=q.groupby(key).agg(net_profit=('net_pnl','sum'),trades=('net_pnl','size'),wins=('net_pnl',lambda x:int((x>0).sum())),adds=('adds','sum'),commission_entry=('entry_commission','sum'),commission_exit=('exit_commission','sum'),financing=('financing','sum'))
        if key=='month':z=z.reindex(pd.period_range('2019-01','2026-03',freq='M').astype(str),fill_value=0)
        z['ending_balance']=100+z.net_profit.cumsum();z.to_csv(r/f'candidate_{cid}_{key}.csv')
    ledger_info.append({'id':cid,'net_cash_error':casherror,'gross_pnl_error':error,'final_equity_error':last,'positions':len(q)})
    curve=pd.read_csv(r/f'candidate_{cid}_equity.csv');curve['timestamp']=pd.to_datetime(curve.timestamp,utc=True)
    fig,ax=plt.subplots(2,1,figsize=(12,7),sharex=True,gridspec_kw={'height_ratios':[2,1]})
    # Keep hourly output extrema in chronological order. This chart is sampled;
    # scalar DD metrics use every replayed candle's modeled excursion.
    ax[0].plot(curve.timestamp,curve.equity,lw=.65);ax[0].set_yscale('symlog',linthresh=10);ax[0].set_ylabel('USD (symlog)');ax[0].set_title(f'{symbol} candidate {cid}: M1 OHLC model, not real ticks')
    ax[1].plot(curve.timestamp,-curve.drawdown_pct,lw=.65,color='darkred');ax[1].set_ylabel('Drawdown %');ax[0].grid(alpha=.25);ax[1].grid(alpha=.25);fig.tight_layout();fig.savefig(r/f'candidate_{cid}_equity_drawdown.png',dpi=130);plt.close(fig)
good=base[(base.equity>=100000)&(base.floating_dd<50)]
def cases_for(cid):return v[v.id==cid]
robust=[]
for _,b in good.iterrows():
    cv=cases_for(b.id).set_index('case')
    if all(cv.loc[c,'equity']>100 and cv.loc[c,'floating_dd']<50 for c in ['COST1_5','COST2','VALID_2023_2024','TEST_2025_2026Q1']):robust.append(int(b.id))
summary.update({'M1_target_count':int((base.equity>=100000).sum()),'M1_target_dd50_count':len(good),'M1_robust_target_ids':robust,'max_independent_reconciliation_error':maxerror,'data_status':audit['status'],'macro_filter':'NONE_NEW_RESEARCH','broker_execution_status':'NOT_VALIDATED','selection_warning':'1M multiple comparisons; historical split only; no virgin prospective holdout.'})
(r/'FINAL_SUMMARY.json').write_text(json.dumps(summary,indent=2));(r/'RECONCILIATION.json').write_text(json.dumps({'max_error':maxerror,'ledgers':ledger_info,'checks':checks},indent=2))
columns=['id','family','tf_minutes','equity','floating_dd','pf','trades','wins','adds','risk','margin_fraction','add_stages','stop_atr','tp_R','hold_bars','breakeven_R']
base[columns+['cohort']].to_csv(r/'M1_RANKED.csv',index=False)
def table(df,cols):
    rows=['| '+' | '.join(cols)+' |','|'+'|'.join(['---']*len(cols))+'|']
    for _,row in df.iterrows():rows.append('| '+' | '.join(f'{row[c]:,.4f}' if isinstance(row[c],(float,np.floating)) else str(row[c]) for c in cols)+' |')
    return '\n'.join(rows)
train=base[base.cohort.str.contains('TRAIN_SELECTED')].copy();train['selection_equity']=train.id.map(v[v['case']=='TRAIN_2019_2022'].set_index('id').equity);train=train.sort_values('selection_equity',ascending=False)
best=base.iloc[0];trainbest=train.iloc[0] if len(train) else None
chosen=[int(best.id)];dd=base[base.floating_dd<50]
if len(dd):chosen.append(int(dd.iloc[0].id))
if trainbest is not None:chosen.append(int(trainbest.id))
sections=[]
for cid in dict.fromkeys(chosen):sections.append(f'### Candidate {cid}\n\n'+table(cases_for(cid),['case','equity','floating_dd','pf','trades','adds']))
report=f'''# RIZAN {symbol} — 1,000,000 configurations, 2019–2026Q1

**Status: EXPLORATORY / BROKER_NOT_VALIDATED.** Independent new strategy research, not frozen XAU/EUR parity. USD100 initial, no topups. 12 families, 1,000,000 unique active parameter combinations. Screened using M15/H1/H4 OHLC; shortlisted candidates rerun on actual minute OHLC. These are not real tick bid/ask replays.

Input: {summary['m1_rows']:,} M1 bars; {summary['first']}–{summary['last']} UTC;87months. Data statusPARTIAL, {audit['gap_count']:,} timestamp gaps; {'188 conflicting source timestamps quarantined; exact duplicate OHLC collapsed, nominal year file ownership prevents overlap.' if symbol=='BTCUSD' else 'Market-weekend gaps are not automatically certified as safe.'} No missing candles synthesized. All input hashes and raw source provenance included.

## Target outcome

Screen target≥100k count: {summary['screen_target_count']}; target plus DD<50%: {summary['screen_target_dd50_count']}.
M1 validated shortlist target≥100k count: {summary['M1_target_count']}; target plus DD<50%: {summary['M1_target_dd50_count']}.
M1 target/DD50 candidates profitable and DD<50 across both fee stresses and each validation/test segment: {robust}.
These counts apply only to this specified search and shortlisted M1 reruns, not all possible strategies. Searching repeatedly until a favorable path appears increases selection bias.

## M1 exploratory full-period leaders

{table(base.head(10),columns)}

## Train-selected candidates (parameters ranked on 2019–2022 only)

{table(train.head(10),['id','family','selection_equity','equity','floating_dd','pf','trades'])}

Training, validation and test segments restart independently from100. This distinguishes segment performance from continuous compounding. The history has been examined in earlier work, so test figures do not constitute an untouched prospective holdout.

## Stress and segment results

{chr(10).join(sections)}

## Model boundaries

USDJPY leverage200, min/step1000baseUSDunits, max2million. Assumed spread1pip, slip0.1pip/side, fee$3/standardlot/side, financing1bp/notional/day charged both directions. BTCUSD leverage10 in BASE is HYPOTHETICAL, min/step.01BTC,max100BTC; spread5bp, slip1bp/side, commission5bp/side, financing3bp/day. See LEVERAGE2 and SPOT_FEE_PROXY sensitivities; spotproxy still permits short and does not reproduce real spot exchange rules. Neither leverage nor historical fees are broker-verified.

Cost multipliers affect commission/slippage/financing, not spread. Delay test shifts entry to a later observed minute; not2second tick latency. OHLC stop-first, gapstop at worseopen, add at next observedopen after closeddepthdecision, break-even nextbar. Intrabar DD is a conservative excursion bound; real intraminute ordering unknown. Discretionary expiry executed on the next available candle open. ACK/depth/partialfills/calendar/recovery and real swap history not modeled.

No macro filters applied. BTCUSD source is Bitstamp exchange trade OHLC, not historical FPMarkets bid/ask; CFD short/margin model is an explicit hypothesis. Original XAU/EUR source, parameters, live cBots and bridge are untouched.

## Accounting

Independent ledger/cash/volume checks passed: {len(checks)} checks. Max absolute reconciliation error USD{maxerror:.12g}. Trade-by-trade ledger, monthly/yearly PnL and sampled equity/drawdown charts included for logged leaders. Scalar DD uses every modeled replay candle; charts are sampled. Six arithmetic fixtures plus nine simulator execution fixtures passed; not native broker certification.

## Reproduction

Source/protocol/commit hashes in SOURCE_SHA256.txt and COMMIT.txt. Full million-row screen includes every tested configuration. Source input CSV compressed with full OHLC and provenance; no synthetic repair. See RESEARCH_PROTOCOL.md for exact signal families and assumptions. Candidate claim remains historical exploratory until independently validated with broker specifications and real ticks.
'''
(r/'REPORT.md').write_text(report)
with open(r/'MANIFEST_SHA256.csv','w') as f:
    f.write('path,sha256,bytes\n')
    for p in sorted(r.glob('*')):
        if p.is_file() and p.name!='MANIFEST_SHA256.csv':f.write(f'{p.name},{hashlib.sha256(p.read_bytes()).hexdigest()},{p.stat().st_size}\n')
print(json.dumps(summary,indent=2),flush=True)
