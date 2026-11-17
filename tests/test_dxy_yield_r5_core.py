"""Synthetic integration tests; none of these examples are backtest evidence."""
import unittest
import numpy as np,pandas as pd
from research.zone_rebound.dxy_yield_r5 import MACROS,macro_fields,macro_mask
from research.zone_rebound.r5_entry_core import entry_events,outcomes

def source(series,side):
    ix=pd.date_range('2026-11-16T12:00:00Z',periods=30,freq='5min');step=.02 if series=='DXY' else .005
    return pd.DataFrame(dict(observed_at=[x.isoformat() for x in ix],available_at=[x.isoformat() for x in ix],value=(100 if series=='DXY' else 4.5)-side*np.arange(len(ix))*step,series=series,unit='INDEX_POINTS' if series=='DXY' else 'PERCENT',instrument_kind='CASH_INDEX' if series=='DXY' else 'CASH_YIELD',source='ICE_DXY' if series=='DXY' else 'TIMESTAMPED_CASH_YIELD',frequency='INTRADAY',time_basis='OBSERVED_INGEST'))

def scenario(side=1):
    ix=pd.date_range('2026-11-16T13:30:00Z',periods=18,freq='min')
    d=pd.DataFrame({'open':101.8,'high':102.,'low':100.7,'close':101.8,'spread':.1},index=ix)
    d.loc[ix[0],['open','high','low','close']]=[103.,103.,100.,101.]
    d.loc[ix[1],['open','high','low','close']]=[101.,101.6,100.2,101.5]
    d.loc[ix[2],['open','high','low','close']]=[101.5,102.,100.7,101.8]
    d.loc[ix[5],'high']=113.
    lo,hi=100.,102.
    if side==-1:
        old=d.copy();d['open']=204-old.open;d['close']=204-old.close;d['high']=204-old.low;d['low']=204-old.high;lo,hi=102.,104.
    q=pd.DataFrame({'i':[0],'side':[side],'lo':[lo],'hi':[hi],'reference':[102.],'atr_h1':[4.],'pub_ns':[ix[0].value-60_000_000_000],'family':['TEST_ZONE'],'tf':[60],'time_ns':[ix[0].value]})
    return d,q

class CoreTests(unittest.TestCase):
    def test_dxy_yield_rules_reach_zone_entry_and_outcome_for_both_sides(self):
        for side in (1,-1):
            d,q=scenario(side);f=macro_fields(d.index.asi8,source('DXY',side),source('US10Y',side))
            e=entry_events(d,q,f,macros=MACROS,mask_fn=macro_mask);z=e[(e.trigger=='INSIDE_REJECT')&(e.macro=='DXY_US10Y')]
            self.assertEqual(len(z),1);self.assertEqual(int(z.i.iloc[0]),2);self.assertFalse(any('eur' in x.lower() for x in e.columns))
            self.assertEqual(int(outcomes(d,z)['state10'][0]),1)
            self.assertFalse((e.macro=='DXY_BOTH_YIELDS').any())

    def test_missing_common_macro_blocks_entry_including_control(self):
        d,q=scenario();f=macro_fields(d.index.asi8,source('DXY',1).iloc[:0],source('US10Y',1))
        self.assertTrue(entry_events(d,q,f,macros=MACROS,mask_fn=macro_mask).empty)

if __name__=='__main__':unittest.main()
