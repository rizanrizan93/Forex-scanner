import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
from fx_scanner.daily_reversal import CONFIGURATIONS,features,events,MIN_RR
from fx_scanner.reversal_zones import normalize_bars

spec=importlib.util.spec_from_file_location('major_research',Path(__file__).parents[1]/'scripts/research_daily_reversal.py')
research=importlib.util.module_from_spec(spec);spec.loader.exec_module(research)


def fixture():
    t=pd.date_range('2020-01-01',periods=45*1440,freq='min',tz='UTC')
    rng=np.random.default_rng(77);c=1500+np.cumsum(rng.normal(0,.15,len(t)));o=np.r_[c[0],c[:-1]]
    return pd.DataFrame(dict(timestamp=t,open=o,high=np.maximum(o,c)+.1,low=np.minimum(o,c)-.1,close=c))


def run(high=105.,low=100.,close=100.,adr=10.,side=1):
    times=np.arange(12*3600,21*3600,60,dtype=np.int64)
    return research.simulate(times,np.full(len(times),100.),np.full(len(times),high),np.full(len(times),low),
        np.full(len(times),close),np.array([0]),np.array([100.]),np.array([3.]),np.array([adr]),side)


def test_grid_is_10_million_and_major_daily_target():
    assert CONFIGURATIONS==10_000_000
    assert research.GRID['target_adr_fraction']==[.25,.35,.5,.75,1.]


def test_net_rr_guard_uses_daily_target_and_costs():
    _,s,_=run()
    for si in range(5):
        for ti in range(5):
            move=research.GRID['target_adr_fraction'][ti]*10
            rr=(move-.2)/(research.GRID['stop_extension_atr'][si]*3+1.4)
            assert ((s[0,si,ti,0]!=-8).any()) == (rr>=MIN_RR)


def test_spread_and_slippage_change_net_fills():
    r,s,risk=run(high=120.)
    # A large target, tight stop and enough bar high resolve in all scenarios.
    assert np.all(s[0,0,4,0]==1)
    assert r[0,0,4,0,0]>r[0,0,4,0,1]>r[0,0,4,0,2]


def test_stop_first_ambiguity_and_gap_fill():
    r,s,_=run(high=120.,low=90.)
    assert np.all(s[0,0,4,0]==-1)
    assert np.all(r[0,0,4,0]<-1.)  # exit slip charged, no optimistic exact -1R


def test_timeout_closes_mark_to_market_instead_of_counting_loss():
    r,s,_=run(high=100.2,low=99.9,close=100.1)
    assert np.all(s[0,1,4,0]==0)
    assert not np.isclose(r[0,1,4,0,1],-1.)
    assert r[0,1,4,0,1]<0  # small favorable bid move still loses after costs
    assert np.isclose(r[0,1,4,0,1],-.7/(.1*3+.6))


def test_future_d1_m15_h1_features_cannot_change_prefix():
    f=fixture();cut=pd.Timestamp('2020-02-10T12:00Z')
    a=features(normalize_bars(f))
    changed=f.copy();changed.loc[changed.timestamp>=cut,['open','high','low','close']]+=1000
    b=features(normalize_bars(changed))
    pd.testing.assert_frame_equal(a.loc[:cut],b.loc[:cut])


def test_sweeps_reclaim_known_anchor_with_structural_stop():
    f=features(normalize_bars(fixture()))
    for side in [1,-1]:
        e=events(f,side,'PREV_D1',.05)
        assert len(e)>0
        assert np.all(e.sweep_depth>.05)
        assert np.all(side*(e.close-e.anchor)>=.025*e.atr)
        assert np.all(side*(e.anchor-e.level)>0)
        assert np.all(e.adr20>0)


def test_session_anchor_unavailable_before_session_complete():
    f=features(normalize_bars(fixture()))
    # M5 close 06:00 opens at05:55, so completed Asia anchor is not available yet.
    for stamp in ['2020-02-10T05:55Z','2020-02-10T06:00Z']:
        assert pd.isna(f.loc[stamp,'anchor_1_ASIA_00_06'])
    assert np.isfinite(f.loc['2020-02-10T06:05Z','anchor_1_ASIA_00_06'])
    assert pd.isna(f.loc['2020-02-10T12:00Z','anchor_1_EUROPE_06_12'])
    assert np.isfinite(f.loc['2020-02-10T12:05Z','anchor_1_EUROPE_06_12'])


def test_prior_day_anchor_cannot_include_current_day_extreme():
    m1=normalize_bars(fixture());f=features(m1)
    previous=m1.loc['2020-02-09']
    assert f.loc['2020-02-10T12:00Z','anchor_1_PREV_D1']==previous.low.min()
    assert f.loc['2020-02-10T12:00Z','anchor_-1_PREV_D1']==previous.high.max()



def test_drawdown_uses_chronological_net_r():
    rr=[2.,-1.,-1.,3.]
    rows=[dict(r_cautious=r,r_stress=r-.1,r_reference=r+.1,status=1 if r>0 else -1,
               risk_points=2.,target_points=4.) for r in rr]
    m=research.ledger_metrics(rows)
    assert m['max_drawdown_r']==2.
    assert m['profit_factor']==2.5
    assert m['mean_net_r']==.75


def test_execution_code_not_imported():
    text=(Path(__file__).parents[1]/'scripts/research_daily_reversal.py').read_text()
    assert '.execution' not in text and 'cbot_bridge' not in text


def test_earlier_ineligible_trigger_does_not_block_later_valid_trigger():
    d=np.array([1,1],np.int64);b=np.array([4,4],np.int64)
    r=np.array([[1.,1.,1.],[3.,3.,3.]]);s=np.array([[-8,-8,-8],[1,1,1]],np.int8)
    out=research.first_valid_stats(d,b,b,np.array([0,0]),np.array([2,2]),r,s,np.ones(2),np.ones(2),4.,np.full(2,5.))
    assert out[0,1,0,0,2,0]==1 and out[0,1,0,0,2,4]==3.


def test_censored_first_eligible_trade_is_not_replaced_using_future_outcomes():
    d=np.array([1,1],np.int64);b=np.array([4,4],np.int64)
    r=np.array([[0.,0.,0.],[3.,3.,3.]]);s=np.array([[-9,-9,-9],[1,1,1]],np.int8)
    out=research.first_valid_stats(d,b,b,np.array([0,0]),np.array([2,2]),r,s,np.ones(2),np.ones(2),4.,np.full(2,5.))
    assert out[0,1,0,0,2,0]==0 and out[0,1,0,0,2,13]==1


def test_net_reward_risk_threshold_changes_first_eligible_trade_without_future_selection():
    d=np.array([1,1],np.int64);b=np.array([4,4],np.int64)
    r=np.array([[1.,1.,1.],[3.,3.,3.]]);s=np.ones((2,3),np.int8)
    out=research.first_valid_stats(d,b,b,np.array([0,0]),np.array([2,2]),r,s,np.ones(2),np.ones(2),4.,np.array([1.8,4.2]))
    assert out[0,1,0,0,2,4]==1.
    assert out[0,1,0,4,2,4]==3.
