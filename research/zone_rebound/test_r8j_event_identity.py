"""R8-J research-only falsification tests for cross-horizon event identity.
Run: python -m unittest research/zone_rebound/test_r8j_event_identity.py
These tests intentionally expose a currently missing R8-I invariant.
No market performance or source authenticity is implied.
"""
import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).with_name("r8i_ledger_integrity.py")
spec = importlib.util.spec_from_file_location("r8i_ledger_integrity", MODULE)
r8i = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r8i)
SHA = "a" * 64
FIELDS = ["event_id","event_utc","year","side","horizon","success","xau_source_sha256"]

def row(horizon, **changes):
    r = dict(event_id="sweep-001", event_utc="2024-04-02T10:00:00Z",
             year="2024", side="BUY", horizon=horizon,
             success="true", xau_source_sha256=SHA)
    r.update(changes)
    return r

def run(rows):
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "events.csv"
        with p.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        return r8i.audit(p)

class CrossHorizonIdentity(unittest.TestCase):
    def test_same_event_consistent_across_horizons(self):
        result = run([row("H1"), row("H4", success="false")])
        self.assertEqual(result["n"], 2)

    def test_same_event_must_not_change_timestamp(self):
        with self.assertRaisesRegex(ValueError, "EVENT_IDENTITY_MISMATCH"):
            run([row("H1"), row("H4", event_utc="2024-04-02T10:05:00Z")])

    def test_same_event_must_not_flip_side(self):
        with self.assertRaisesRegex(ValueError, "EVENT_IDENTITY_MISMATCH"):
            run([row("H1"), row("H4", side="SELL")])

    def test_same_event_must_not_change_source_fingerprint(self):
        with self.assertRaisesRegex(ValueError, "EVENT_IDENTITY_MISMATCH"):
            run([row("H1"), row("H4", xau_source_sha256="b"*64)])

if __name__ == "__main__":
    unittest.main()
