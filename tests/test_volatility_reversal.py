import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
from fx_scanner.volatility_reversal import CONFIGURATIONS,features,events,MIN_RR
from fx_scanner.reversal_zones import normalize_bars

spec=importlib.util.spec_from_file_location('major_research',Path(__file__).parents[1]/'scripts/research_volatility_reversal.py')
research=importlib.util.module_from_spec(spec);spec.loader.exec_module(research)


def fixture():
    t=pd.date_range('2020-01-01',periods=45*1440,freq='min',tz='UTC')
    rng=np.random.default_rng(77);c=1500+np.cumsum(rng.normal(0,.15,len(t)));o=np.r_[c[0],c[:-1]]
    return pd.DataFrame(dict(timestamp=t,open=o,high=np.maximum(o,c)+.1,low=np.minimum(o,c)-.1,close=c))


def run(high=105.,low=100.,close=100.,adr=10.,side=1):
    times=np.arange(12*3600,21*3600,60,dtype=np.int64)
    return research.simulate(times,np.full(len(times),100.),np.full(len(times),high),np.full(len(times),low),
        np.full(len(times),close),np.array([0]),np.array([100.]),np.array([3.]),np.array([adr]),side)


def test_grid_and_r_targets():
    assert CONFIGURATIONS==10_000_000
    assert research.GRID['target_r']==[1.5,2.,3.,4.,6.6]


def test_rr_and_daily_target_at_entry():
    r,s,risk=run(adr=1000.)
    assert np.all(s==-8)
    _,s,risk=run(adr=10.)
    for si in range(5):
        for ti in range(5):
            nominal=max(.5,research.GRID['stop_atr5_multiple'][si]*3,.6)
            move=research.GRID['target_r'][ti]*nominal
            eligible=move>=2.5 and (move-.2)/(nominal+.8)>=MIN_RR
            assert ((s[0,si,ti,0]!=-8).any())==eligible



def test_spread_and_slippage_change_net_fills():
    r,s,risk=run(high=180.)
    # A large target, tight stop and enough bar high resolve in all scenarios.
    assert np.all(s[0,0,4,0]==1)
    assert r[0,0,4,0,0]>r[0,0,4,0,1]>r[0,0,4,0,2]


def test_stop_first_ambiguity_and_gap_fill():
    r,s,_=run(high=180.,low=90.)
    assert np.all(s[0,0,4,0]==-1)
    assert np.all(r[0,0,4,0]<-1.)  # exit slip charged, no optimistic exact -1R


def test_timeout_closes_mark_to_market_instead_of_counting_loss():
    r,s,_=run(high=100.2,low=99.9,close=100.1)
    assert np.all(s[0,1,4,0]==0)
    assert not np.isclose(r[0,1,4,0,1],-1.)
    assert r[0,1,4,0,1]<0  # small favorable bid move still loses after costs
    assert np.isclose(r[0,1,4,0,1],-.7/(1.65*3))


def test_future_d1_m15_h1_features_cannot_change_prefix():
    f=fixture();cut=pd.Timestamp('2020-02-10T12:00Z')
    a=features(normalize_bars(f))
    changed=f.copy();changed.loc[changed.timestamp>=cut,['open','high','low','close']]+=1000
    b=features(normalize_bars(changed))
    pd.testing.assert_frame_equal(a.loc[:cut],b.loc[:cut])


def test_major_observations_nonoverlap_and_m15_confirmation():
    f=features(normalize_bars(fixture()))
    for side in [1,-1]:
        e=events(f,side,'M5_CHANNEL_48',1.)
        assert np.all(f.loc[e.index,f'signal_{side}_M5_CHANNEL_48'])
        assert np.all(e.adr20>0)
        assert np.all(e.atr5>=.5)
        assert np.all(e.level==f.loc[e.index,'low' if side==1 else 'high'])


def test_drawdown_uses_chronological_net_r():
    rr=[2.,-1.,-1.,3.]
    rows=[dict(r_cautious=r,r_stress=r-.1,r_reference=r+.1,status=1 if r>0 else -1,
               risk_points=2.,target_points=4.) for r in rr]
    m=research.ledger_metrics(rows)
    assert m['max_drawdown_r']==2.
    assert m['profit_factor']==2.5
    assert m['mean_net_r']==.75


def test_execution_code_not_imported():
    text=(Path(__file__).parents[1]/'scripts/research_volatility_reversal.py').read_text()
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


def test_volatility_floor_uses_closed_trigger_and_is_nested():
    f=features(normalize_bars(fixture()))
    loose=events(f,1,'M5_CHANNEL_48',0.)
    strict=events(f,1,'M5_CHANNEL_48',2.)
    assert strict.index.isin(loose.index).all()
    assert (strict.atr5>=1.).all()

