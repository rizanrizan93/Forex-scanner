import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np,pandas as pd
import profit_engine as pe

class Tests(unittest.TestCase):
    def fixture(self,n=8000):
        t=np.arange(n)*1000;q=np.column_stack([np.full(n,100.),np.full(n,100.)])
        e={'side':1,'stop':99.,'atr':1.};en,_=pe.entry(e,0,t,q)
        return e,en,t,q

    def test_baseline_matches_v2_cash_model(self):
        e,en,t,q=self.fixture();q[100:]=[101.2,101.2]
        old=pe.v2.simulate(e,0,t,q,60);new,_=pe.simulate(e,en,t,q,{'tp_R':1,'hold_min':60})
        for k in ['entry_ms','exit_ms','gross_R','cost_R','net_R_1x','net_R_1.5x','net_R_2x']:
            self.assertAlmostEqual(old[k],new[k])

    def test_stop_gap_uses_worse_quote(self):
        e,en,t,q=self.fixture();q[10:]=[98,98]
        r,_=pe.simulate(e,en,t,q,{'tp_R':2,'hold_min':120})
        self.assertEqual(r['reason'],'STOP');self.assertEqual(r['gross_R'],-2)

    def test_short_side_sign(self):
        e,en,t,q=self.fixture();e['side']=-1;e['stop']=101;en,_=pe.entry(e,0,t,q);q[10:]=[98,98]
        r,_=pe.simulate(e,en,t,q,{'tp_R':2,'hold_min':120})
        self.assertEqual(r['reason'],'TARGET');self.assertEqual(r['gross_R'],2)

    def test_partial_weighted_profit(self):
        e,en,t,q=self.fixture();q[10:20]=[101,101];q[20:]=[102,102]
        r,legs=pe.simulate(e,en,t,q,{'tp_R':2,'hold_min':120,'partial_at_R':1,'partial_fraction':.5})
        self.assertEqual(len(legs),2);self.assertEqual(r['gross_R'],1.5)
        self.assertEqual(sum(x['fraction'] for x in legs),1)

    def test_partial_entry_fee_charged_once(self):
        e,en,t,q=self.fixture();q[10:20]=[101,101];q[20:]=[102,102]
        r,_=pe.simulate(e,en,t,q,{'tp_R':2,'hold_min':120,'partial_at_R':1,'partial_fraction':.5})
        duration=.5*(10000-en['entry_ms'])/1000+.5*(20000-en['entry_ms'])/1000
        expect=(100+.5*101+.5*102)*.00065+100*.0003*duration/86400
        self.assertAlmostEqual(r['cost_usd_per_initial_btc'],expect)

    def test_partial_then_stop_is_not_full_profit(self):
        e,en,t,q=self.fixture();q[10:20]=[101,101];q[20:]=[99,99]
        r,_=pe.simulate(e,en,t,q,{'tp_R':2,'hold_min':120,'partial_at_R':1,'partial_fraction':.5})
        self.assertEqual(r['gross_R'],0);self.assertLess(r['net_R_1x'],0)

    def test_price_break_even_still_pays_costs(self):
        e,en,t,q=self.fixture();q[10]=[101,101];q[11:]=[100,100]
        r,_=pe.simulate(e,en,t,q,{'tp_R':2,'hold_min':120,'be_after_R':1})
        self.assertEqual(r['exit_ms'],11000);self.assertEqual(r['gross_R'],0);self.assertLess(r['net_R_1x'],0)

    def test_trailing_effective_next_quote_and_future_invariant(self):
        e,en,t,q=self.fixture();q[10]=[101.2,101.2];q[11]=[100.4,100.4]
        p={'tp_R':2,'hold_min':120,'trail_after_R':1,'trail_distance_R':.75}
        r,_=pe.simulate(e,en,t,q,p);q[12:]=[500,500];later,_=pe.simulate(e,en,t,q,p)
        self.assertEqual(r,later);self.assertEqual(r['exit_ms'],11000)

    def test_time_protect_at30min(self):
        e,en,t,q=self.fixture();q[:]=[100.1,100.1];q[en['j']]=[100,100]
        r,_=pe.simulate(e,en,t,q,{'tp_R':2,'hold_min':120,'protect_after_min':30,'required_mfe_R':.5})
        self.assertEqual(r['reason'],'TIME_PROTECT');self.assertEqual(r['weighted_duration_s'],1800)

    def test_time_protect_preserves_trade_if_mfe_sufficient(self):
        e,en,t,q=self.fixture();q[10]=[100.6,100.6]
        r,_=pe.simulate(e,en,t,q,{'tp_R':2,'hold_min':120,'protect_after_min':30,'required_mfe_R':.5})
        self.assertEqual(r['reason'],'TIMEOUT');self.assertEqual(r['weighted_duration_s'],7200)

    def test_right_edge_is_censored_not_forced_profit(self):
        e,en,t,q=self.fixture(n=100)
        r,legs=pe.simulate(e,en,t,q,{'tp_R':2,'hold_min':120})
        self.assertEqual(r['status'],'RIGHT_CENSORED');self.assertEqual(legs,[]);self.assertFalse(en['primary_eligible'])

    def test_structural_cap_and_fallback(self):
        e,en,t,q=self.fixture();e['opposing_target_at_touch']=100.8;q[10:]=[100.8,100.8]
        r,_=pe.simulate(e,en,t,q,{'tp_R':2,'hold_min':120,'structural_cap':True})
        self.assertAlmostEqual(r['target_R'],.8);self.assertTrue(r['structural_target_used'])
        e['opposing_target_at_touch']=None
        z,_=pe.simulate(e,en,t,q,{'tp_R':2,'hold_min':120,'structural_cap':True})
        self.assertEqual(z['target_R'],2);self.assertTrue(z['structural_fallback'])

    def test_stress_monotone_same_fill(self):
        e,en,t,q=self.fixture();q[10:]=[102,102]
        r,_=pe.simulate(e,en,t,q,{'tp_R':2,'hold_min':120})
        self.assertGreater(r['net_R_1x'],r['net_R_1.5x']);self.assertGreater(r['net_R_1.5x'],r['net_R_2x'])
        self.assertEqual(r['entry_px'],100);self.assertEqual(r['gross_R'],2)

    def test_common_cohort_rejects_future_missing_window(self):
        e,en,t,q=self.fixture();q[7000]=np.nan
        x,_=pe.entry(e,0,t,q);self.assertFalse(x['primary_eligible'])

    def test_selection_never_uses_validation_profit(self):
        rows=[]
        for policy,score in [('A',.2),('B',.1)]:
            for cost in [1,1.5]:rows.append({'split':'training','policy':policy,'scope':'one_position','cost_multiple':cost,'n':6,
                'mean_net_R':score,'PF_R':2,'R_per_opportunity':score,'max_cumulative_R_DD':1})
        rows.append({**rows[0],'split':'new_validation','policy':'B','R_per_opportunity':1e9,'mean_net_R':1e9})
        with tempfile.TemporaryDirectory() as tmp,patch.object(pe,'ROOT',Path(tmp)):
            (Path(tmp)/'LOCKED_PROTOCOL_V3.json').write_text('{}')
            result=pe.select(pd.DataFrame(rows))
        self.assertEqual(result['policy'],'A');self.assertFalse(result['new_validation_results_seen_at_selection'])

if __name__=='__main__':unittest.main(verbosity=2)
