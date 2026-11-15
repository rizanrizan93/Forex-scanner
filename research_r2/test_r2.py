import sys,pathlib,unittest,numpy as np,pandas as pd
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'research_r1'))
from signals_r2 import prepare,signals,candidates,FAMILIES
from acquire_vintages import validate
class Causality(unittest.TestCase):
 def test_all_families_prefix_invariant(self):
  rng=np.random.default_rng(9);n=6000;price=1800+np.cumsum(rng.normal(0,.5,n));idx=pd.date_range('2020-01-01',periods=n,freq='5min',tz='UTC')
  b=pd.DataFrame({'open':price-.1,'high':price+.4,'low':price-.4,'close':price,'ticks':20,'max_gap_ms':1000,'first_tick':idx.as_unit('ms').asi8,'last_tick':idx.as_unit('ms').asi8+299000},index=idx)
  e=pd.DataFrame({'eur':1.1+np.arange(n)*.000001,'quote_ms':idx.as_unit('ms').asi8+299000},index=idx)
  full=prepare(b,e);prefix=prepare(b.iloc[:5500],e.iloc[:5500]);cut=idx[5500]+pd.Timedelta(minutes=5)
  for family in FAMILIES:
   for usd in [0,1]:
    c={'family':family,'window':'FULL','stop':1.25,'target':2.,'usd':usd}
    a=signals(full,c);a=a[a.signal_ms<cut.timestamp()*1000];p=signals(prefix,c);pd.testing.assert_frame_equal(a,p,check_freq=False)
  self.assertTrue((full.h1_age_ms.dropna()>=0).all());self.assertTrue((full.m15_age_ms.dropna()>=0).all())
 def test_reject_mixed_latest_vintage(self):
  raw=b'observation_date,DGS2_20190104,DGS10_20261115,DFII10_20261115\n2019-01-03,2.39,2.56,.88\n'
  with self.assertRaises(ValueError):validate(raw,pd.Timestamp('2019-01-04'))
 def test_accept_verified_vintage(self):
  raw=b'observation_date,DGS2_20190104,DGS10_20190104,DFII10_20190104\n2019-01-03,2.39,2.56,.88\n';self.assertEqual(len(validate(raw,pd.Timestamp('2019-01-04'))),1)
if __name__=='__main__':unittest.main(verbosity=2)
