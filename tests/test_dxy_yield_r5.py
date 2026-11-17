import json,unittest
import numpy as np
import pandas as pd
from research.zone_rebound.dxy_yield_r5 import REQUIRED,MIN,validate_points,normalize_yahoo,macro_fields,macro_mask,preflight

def points(series,*,rising=False,delay=0):
    ix=pd.date_range('2026-11-16T12:00:00Z',periods=30,freq='5min');step=.02 if series=='DXY' else .005
    values=(100 if series=='DXY' else 4.5)+(1 if rising else -1)*np.arange(len(ix))*step
    return pd.DataFrame(dict(observed_at=[x.isoformat() for x in ix],available_at=[(x+pd.Timedelta(minutes=delay)).isoformat() for x in ix],value=values,series=series,unit='INDEX_POINTS' if series=='DXY' else 'PERCENT',instrument_kind='CASH_INDEX' if series=='DXY' else 'CASH_YIELD',source='ICE_DXY' if series=='DXY' else 'TIMESTAMPED_CASH_YIELD',frequency='INTRADAY',time_basis='OBSERVED_INGEST'))

class DxyYieldTests(unittest.TestCase):
    def test_down_index_and_yield_support_buy(self):
        t=np.array([pd.Timestamp('2026-11-16T13:30:00Z').value]);f=macro_fields(t,points('DXY'),points('US10Y'))
        self.assertTrue(macro_mask('DXY_US10Y',f,1)[0]);self.assertFalse(macro_mask('DXY_US10Y',f,-1)[0])
        self.assertAlmostEqual(f['US10Y_15'][0],-1.5)

    def test_up_index_and_yield_support_sell(self):
        t=np.array([pd.Timestamp('2026-11-16T13:30:00Z').value]);f=macro_fields(t,points('DXY',rising=True),points('US10Y',rising=True))
        self.assertTrue(macro_mask('DXY_US10Y',f,-1)[0]);self.assertFalse(macro_mask('DXY_US10Y',f,1)[0])

    def test_conflict_does_not_pass_both(self):
        t=np.array([pd.Timestamp('2026-11-16T13:30:00Z').value]);f=macro_fields(t,points('DXY'),points('US10Y',rising=True))
        self.assertFalse(macro_mask('DXY_US10Y',f,1)[0]);self.assertFalse(macro_mask('DXY_US10Y',f,-1)[0])

    def test_missing_optional_2y_blocks_only_three_way_rule(self):
        t=np.array([pd.Timestamp('2026-11-16T13:30:00Z').value]);f=macro_fields(t,points('DXY'),points('US10Y'))
        self.assertTrue(macro_mask('DXY_US10Y',f,1)[0]);self.assertFalse(macro_mask('DXY_BOTH_YIELDS',f,1)[0])

    def test_source_age_blocks_control_and_entry(self):
        t=np.array([pd.Timestamp('2026-11-16T20:30:00Z').value]);f=macro_fields(t,points('DXY'),points('US10Y'))
        self.assertFalse(macro_mask('NONE',f)[0]);self.assertFalse(macro_mask('DXY_US10Y',f)[0])

    def test_no_eur_synthetic_futures_or_daily_replacement(self):
        for field,value in [('series','EURUSD'),('source','CTRADER_SYNTHETIC_USDX_6FX'),('instrument_kind','FUTURES'),('frequency','DAILY')]:
            q=points('DXY');q[field]=value
            with self.assertRaises(ValueError):validate_points(q,'DXY')

    def test_delayed_data_is_not_available_at_observation(self):
        t=np.array([pd.Timestamp('2026-11-16T13:30:00Z').value]);q=points('US10Y',delay=30);f=macro_fields(t,points('DXY'),q)
        self.assertFalse(f['common_fresh'][0])

    def test_future_quotes_do_not_change_past_features(self):
        dx=points('DXY');y=points('US10Y');t=np.array([pd.Timestamp('2026-11-16T13:30:00Z').value]);a=macro_fields(t,dx.iloc[:20],y.iloc[:20]);dx.loc[20:,'value']=900;y.loc[20:,'value']=30;b=macro_fields(t,dx,y)
        for key in a:np.testing.assert_allclose(a[key],b[key],equal_nan=True)

    def test_timezone_and_publication_order_required(self):
        q=points('DXY');q['available_at']='2026-11-16T10:00:00'
        with self.assertRaises(ValueError):validate_points(q,'DXY')
        q=points('DXY');q['available_at']='2026-11-15T10:00:00Z'
        with self.assertRaises(ValueError):validate_points(q,'DXY')

    def test_yahoo_metadata_bar_close_and_partial_snapshot(self):
        ix=pd.Timestamp('2026-11-16T12:00:00Z').value//1_000_000_000
        q={'chart':{'result':[{'meta':{'symbol':'DX-Y.NYB','instrumentType':'INDEX','dataGranularity':'5m'},'timestamp':[ix,ix+300,ix+333],'indicators':{'quote':[{'close':[100.,99.9,99.8]}]}}]}}
        f=normalize_yahoo(q,'DXY',fetched_at='2026-11-16T12:06:00Z');self.assertEqual(len(f),1);self.assertEqual(f.observed_at.iloc[0],pd.Timestamp('2026-11-16T12:05:00Z'));self.assertEqual(f.available_at.iloc[0],pd.Timestamp('2026-11-16T12:06:00Z'))
        q['chart']['result'][0]['meta']['symbol']='DX=F'
        with self.assertRaises(ValueError):normalize_yahoo(q,'DXY',fetched_at='2026-11-16T13:00:00Z')

    def test_old_quote_cannot_overwrite_current_observation(self):
        q=points('DXY');late=q.iloc[[0]].copy();late['available_at']='2026-11-16T16:00:00Z';q=pd.concat([q,late],ignore_index=True);self.assertEqual(len(validate_points(q,'DXY')),30)

    def test_vendor_snapshot_time_excludes_unfinished_bar_even_if_download_is_late(self):
        ix=pd.Timestamp('2026-11-16T12:00:00Z').value//1_000_000_000
        q={'chart':{'result':[{'meta':{'symbol':'DX-Y.NYB','instrumentType':'INDEX','dataGranularity':'5m','regularMarketTime':ix+360},'timestamp':[ix,ix+300],'indicators':{'quote':[{'close':[100.,99.9]}]}}]}}
        f=normalize_yahoo(q,'DXY',fetched_at='2026-11-16T15:00:00Z');self.assertEqual(len(f),1)

    def test_coverage_is_not_an_accuracy_result(self):
        q=pd.DataFrame({'time_ns':[pd.Timestamp('2025-01-01T12:00:00Z').value]});p=preflight(q,points('DXY'),points('US10Y'))
        self.assertEqual(p['status'],'NEED_MATCHED_INTRADAY_HISTORY');self.assertFalse(p['accuracy_computed']);self.assertFalse(p['eur_or_synthetic_fallback'])

if __name__=='__main__':unittest.main()
