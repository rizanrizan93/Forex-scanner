"""Deterministic synthetic sequence tests; no financial performance claims."""
import copy
import pandas as pd
from fx_scanner.manual_precision_shadow import watch

def test_precision_states():
    start=pd.Timestamp('2026-11-25 10:00:00Z')
    issue=start+pd.Timedelta(minutes=90)
    idx=pd.date_range(start,periods=110,freq='min')
    f=pd.DataFrame({'open':101.,'high':101.4,'low':100.9,'close':101.1},index=idx)
    f.loc[issue]=[101,101.3,99.8,101.15]
    for i in range(95,100): f.iloc[i]=[101.1,103.,101.,102.8]
    f.iloc[100]=[101.35,102,101.3,101.8]
    f.iloc[101:]=[101.8,102,101.6,101.9]
    z={'tf':'H1','direction':'BUY','execution_authority':False,'low':100.,'high':100.5,'invalidation':99.,'formed_at':start.isoformat()}
    row={'tf':'H1','direction':'BUY','execution_authority':False,'state':'WATCH_ZONE','zones':[z]}
    model={'tf':'H1','direction':'BUY','status':'ACTIVE_SHADOW','execution_authority':False,'issued':issue.isoformat(),'target':(issue+pd.Timedelta(hours=1)).isoformat()}
    def check(name,expected,minute=101,mutate=None,side='BUY'):
        now=start+pd.Timedelta(minutes=minute)
        r=copy.deepcopy(row);m=copy.deepcopy(model)
        market={'frame':f.copy(),'as_of':now,'quote_as_of':now,'bid':101.75,'ask':101.8}
        if side=='SELL':
            for k in ['open','close']:market['frame'][k]=200-market['frame'][k]
            l=market['frame'].low.copy()
            market['frame']['low']=200-market['frame'].high
            market['frame']['high']=200-l
            market['bid'],market['ask']=98.2,98.25
            r['direction']=m['direction']=r['zones'][0]['direction']='SELL'
            r['zones'][0].update(low=99.5,high=100.,invalidation=101.)
        if mutate:mutate(r,m,market,now)
        out=watch(r,m,market,now=now)
        assert out['state']==expected,(name,out)
        assert out['execution_authority'] is False
        assert out['entry_reference'] is None and out['probability'] is None
    check('no touch','APPROACH',90)
    check('sweep','WAIT_MSS',91)
    check('MSS','WAIT_RETEST',100)
    check('complete buy','SHADOW_PATTERN')
    check('complete sell','SHADOW_PATTERN',side='SELL')
    check('expired retest','RETEST_EXPIRED',110)
    check('stale quote','WAIT_DATA',mutate=lambda r,m,k,n:k.update(quote_as_of=n-pd.Timedelta(seconds=31)))
    check('expired bias','WAIT_DIRECTION',mutate=lambda r,m,k,n:m.update(target=n.isoformat()))
    check('wrong timeframe','WAIT_DIRECTION',mutate=lambda r,m,k,n:m.update(tf='H4'))
    check('invalidated','INVALIDATED',mutate=lambda r,m,k,n:k.update(bid=98.9,ask=99.))
