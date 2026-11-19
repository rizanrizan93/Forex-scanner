"""Synthetic integrity tests for R8-F. NOT a market replay."""
import tempfile
import unittest
from pathlib import Path
from r8f_m1_source_gate import audit

class SourceGateTests(unittest.TestCase):
    def fixture(self, text):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p=Path(self.tmp.name)/"m1.csv"
        p.write_text(text,encoding="utf-8")
        return p

    def test_causal_close_and_lag(self):
        p=self.fixture("open_utc,close\n2024-01-02T10:00:00Z,100\n2024-01-02T10:01:00Z,101\n")
        r=audit(p,["2024-01-02T10:02:59Z","2024-01-02T10:03:00Z","2024-01-02T10:04:00Z"])
        self.assertEqual([x["status"] for x in r["asof_events"]],["NO_ASOF_BAR","VALID","VALID"])
        self.assertEqual(r["asof_events"][1]["price"],100)

    def test_gap_is_not_filled(self):
        p=self.fixture("open_utc,close\n2024-01-02T10:00:00Z,100\n2024-01-02T10:03:00Z,101\n")
        self.assertEqual(audit(p)["gap_intervals"],1)

    def test_rejects_unsorted(self):
        p=self.fixture("open_utc,close\n2024-01-02T10:01:00Z,101\n2024-01-02T10:00:00Z,100\n")
        with self.assertRaisesRegex(ValueError,"DUPLICATE_OR_UNSORTED"):audit(p)

    def test_rejects_non_utc(self):
        p=self.fixture("open_utc,close\n2024-01-02T10:00:00+07:00,100\n")
        with self.assertRaisesRegex(ValueError,"UTC_Z_REQUIRED"):audit(p)

    def test_rejects_bad_prices(self):
        p=self.fixture("open_utc,close\n2024-01-02T10:00:00Z,nan\n")
        with self.assertRaisesRegex(ValueError,"INVALID_PRICE"):audit(p)

    def test_stale(self):
        p=self.fixture("open_utc,close\n2024-01-02T10:00:00Z,100\n")
        r=audit(p,["2024-01-02T10:10:00Z"])
        self.assertEqual(r["asof_events"][0]["status"],"STALE")
        self.assertIsNone(r["asof_events"][0]["price"])

if __name__=="__main__":unittest.main()
