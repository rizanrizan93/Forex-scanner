"""Safety regression for the BUY050 resource-only update (no order execution)."""
import pathlib
import random
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
S = ROOT / "source"

def baseline(rows, cutoff):
    return [r for r in rows if r[0] + 1 <= cutoff]

class M1CacheModel:
    def __init__(self):
        self.cached = None
        self.first = None
        self.last = None
        self.full_rebuilds = 0
    def update(self, rows, cutoff):
        valid = baseline(rows, cutoff)
        last = valid[-1][0] if valid else None
        if self.cached is not None and last == self.last:
            return list(self.cached)
        if (self.cached and valid and len(valid)>len(self.cached)
                and valid[0][0]==self.first
                and valid[len(self.cached)-1][0]==self.last):
            self.cached.extend(valid[len(self.cached):])
            self.last=last
            return list(self.cached)
        self.cached=list(valid)
        self.first=valid[0][0] if valid else None
        self.last=last
        self.full_rebuilds+=1
        return list(self.cached)

class RuntimeResilience(unittest.TestCase):
    def test_incremental_candle_replay_and_history_rotation(self):
        rng=random.Random(50050)
        rows=[]
        c=M1CacheModel()
        tick=0
        for k in range(500):
            tick += rng.choice([1,1,1,1,2,3,12])
            rows.append((tick, rng.uniform(1,2)))
            if k and k%150==0:
                rows=rows[10:]
            self.assertEqual(c.update(rows,tick+1),baseline(rows,tick+1))
            self.assertEqual(c.update(rows,tick+1),baseline(rows,tick+1))
        self.assertLess(c.full_rebuilds,10)
    def test_localstorage_startup_failclosed_and_manual_risk_unchanged(self):
        source=(S/"PortfolioHost.cs").read_text()
        self.assertIn('PORTFOLIO_STORAGE_FAULT', source)
        self.assertIn('PORTFOLIO_STORAGE_VERIFY_FAILED', source)
        self.assertIn('var verified=LocalStorage.GetString(key,LocalStorageScope.Instance);', source)
        self.assertIn('if(verified!=settings)', source)
        self.assertIn('if(p.StopLoss==null)return double.PositiveInfinity;', source)
        self.assertIn('!NoForeignExposure()', source)
        self.assertNotIn('LocalStorage.Remove(', source)

    def test_frozen_parameters_and_failsafe_unchanged(self):
        source=(S/"PortfolioHost.cs").read_text()
        for required in ("20.75", "XauTargetR", "XauRiskMultiplier", "OpenRisk()", "NoForeignExposure()", "PortfolioReady", "RIZAN_BTC_TICK_FAULT", "RIZAN_RUNTIME_HEALTH", "OnException(Exception exception)"):
            self.assertIn(required,source)
        self.assertIn("if(p.StopLoss==null)return double.PositiveInfinity;",source)
        for name in ("xau","eur"):
            text=(S/name/"RizanRobot.cs").read_text()
            self.assertIn("for(int i=_closedCache.Count;i<=last;i++)",text)
            self.assertIn("_closedCacheFirstUtc",text)
            self.assertIn("if(now>=_nextCheckpointJournal)",text)
            self.assertIn("Print(\"RIZAN_CHECKPOINT {0}\",Serialize())",text)

if __name__=="__main__":
    unittest.main()
