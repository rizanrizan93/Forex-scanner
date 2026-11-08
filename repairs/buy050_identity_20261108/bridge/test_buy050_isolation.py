import unittest
from pathlib import Path
import server

class IsolationTest(unittest.TestCase):
    def test_profile_pinned_to_buy050(self):
        from json import loads
        expected=loads((Path(__file__).parent.parent/"FROZEN_BUY050_ORIGINAL_UNCHANGED.json").read_text())
        self.assertEqual(server.PROFILE,"13bfa137f962e6d3cf4dd601edfedb15b432653063fa86ec52adadeb4d8ffdf6")
        self.assertEqual(server.CONTRACTS["TPX_13bfa137"][0],"XAUUSD")
        self.assertEqual(server.CONTRACTS["TPE_13bfa137"][0],"EURUSD")
        self.assertEqual(server.identity("TPBTC:"+server.PROFILE+":1237903:BTCUSD")[1],"BTCUSD")
    def test_no_legacy_route_or_state_overwrite(self):
        deploy=Path(__file__).parent/"deploy"
        self.assertFalse((deploy/"rizan-disp1506-bridge.service").exists())
        self.assertTrue((deploy/"rizan-buy050-bridge.service").exists())
        self.assertIn("25352",(deploy/"nginx-buy050-locations.conf").read_text())
        for p in (Path(__file__).parent/"server.py",deploy/"nginx-buy050-locations.conf"):
            self.assertNotIn("/disp1506",p.read_text())
        self.assertIn("RIZAN_BUY050_FROZEN_20261107",(Path(__file__).parent/"server.py").read_text())

if __name__=="__main__": unittest.main()
