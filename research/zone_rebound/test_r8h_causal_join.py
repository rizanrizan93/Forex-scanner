"""R8-H independent causal-window falsification tests (synthetic fixtures only).
Run: python -m unittest discover -s research/zone_rebound -p 'test_r8h*.py'
No market accuracy claims; no production imports.
"""
import csv
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).parent))
from r8g_causal_usd_event_join import join

SHA="a"*64
BASE=datetime(2024,1,2,12,0,tzinfo=timezone.utc)

def stamp(t):return t.strftime("%Y-%m-%dT%H:%M:%SZ")

class CausalJoinTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.m1=Path(self.temp.name)/"usd.csv"
        self.events=Path(self.temp.name)/"events.csv"

    def write(self, missing=(), direction=1, event_offset=63):
        with self.m1.open("w",newline="") as f:
            w=csv.writer(f);w.writerow(["open_utc","close"])
            for i in range(65):
                if i not in missing:w.writerow([stamp(BASE+timedelta(minutes=i)),100+i*direction*.01])
        with self.events.open("w",newline="") as f:
            w=csv.writer(f);w.writerow(["event_id","event_utc","year","side","horizon","success","xau_source_sha256"])
            w.writerow(["e1",stamp(BASE+timedelta(minutes=event_offset)),2024,"SELL","H1","true",SHA])

    def test_consensus_up_and_causal_lag(self):
        self.write(event_offset=67)
        result=join(self.m1,self.events,lag_seconds=120,max_age_seconds=300)
        self.assertEqual(result["per_event_directions"][0]["directions"],{5:"UP",15:"UP",60:"UP"})
        self.assertEqual(result["overall"]["H1"]["SELL"]["n"],1)

    def test_missing_intermediate_bar_abstains(self):
        self.write(missing=(30,),event_offset=67)
        result=join(self.m1,self.events)
        self.assertEqual(result["per_event_directions"][0]["directions"][60],"UNAVAILABLE")
        self.assertEqual(result["overall"]["H1"]["SELL"]["n"],0)

    def test_future_bars_not_used(self):
        self.write(event_offset=62)
        result=join(self.m1,self.events)
        self.assertEqual(result["overall"]["H1"]["SELL"]["n"],0)

    def test_inverse_buy_direction(self):
        self.write(direction=-1,event_offset=67)
        with self.events.open() as f: content=f.read().replace(",SELL,",",BUY,")
        self.events.write_text(content)
        result=join(self.m1,self.events)
        self.assertEqual(result["overall"]["H1"]["BUY"]["n"],1)

if __name__=="__main__":unittest.main()
