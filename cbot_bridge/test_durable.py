"""Checkpoint persistence tests with synthetic identities; never broker execution."""
import json
import tempfile
import unittest
from pathlib import Path

from server import Store, _write_snapshot
from selftest import state


class DurableTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "state.sqlite"
        self.now = 1000
        self.store = Store(self.path, clock=lambda: self.now)
        self.xau = "RZXA1:1:XAUUSD"
        self.eur = "RZEU4B:1:EURUSD"
        self.lease = "a" * 32

    def tearDown(self):
        self.store.db.close()
        self.folder.cleanup()

    def reopen(self):
        self.store.db.close()
        self.store = Store(self.path, clock=lambda: self.now)

    def test_restart_recovery_and_lost_ack(self):
        self.store.acquire(self.xau, self.lease)
        s = state("RZXA1", 1, "XAUUSD", 10)
        s["OpaqueLegState"] = {"a": "filled", "b": "pending"}
        self.assertEqual(self.store.save(self.xau, self.lease, 0, 10, s), 1)
        self.reopen()
        self.assertEqual(self.store.acquire(self.xau, self.lease), (1, s))
        self.assertEqual(self.store.save(self.xau, self.lease, 0, 10, s), 1)
        self.assertEqual(self.store.acquire(self.xau, self.lease), (1, s))

    def test_durable_exclusivity_and_expiry(self):
        self.store.acquire(self.xau, self.lease)
        self.reopen()
        with self.assertRaisesRegex(ValueError, "LEASE_BUSY"):
            self.store.acquire(self.xau, "b" * 32)
        self.now += 46
        self.store.acquire(self.xau, "b" * 32)
        with self.assertRaisesRegex(ValueError, "LEASE_EXPIRED"):
            self.store.touch(self.xau, self.lease)

    def test_namespaces_and_state_conflicts(self):
        for key, prefix, symbol in ((self.xau, "RZXA1", "XAUUSD"),
                                    (self.eur, "RZEU4B", "EURUSD")):
            self.store.acquire(key, self.lease)
            self.assertEqual(self.store.save(key, self.lease, 0, 1, state(prefix, 1, symbol, 1)), 1)
        changed = state("RZXA1", 1, "XAUUSD", 1)
        changed["ChangedLeg"] = True
        with self.assertRaisesRegex(ValueError, "STATE_REVISION_REUSE_CONFLICT"):
            self.store.save(self.xau, self.lease, 0, 1, changed)
        with self.assertRaisesRegex(ValueError, "REVISION_CONFLICT"):
            self.store.save(self.xau, self.lease, 0, 2, state("RZXA1", 1, "XAUUSD", 2))
        self.assertEqual(self.store.status(set())["EURUSD"]["checkpoint_version_max"], 1)

    def test_legacy_retry(self):
        s = state("RZXA1", 1, "XAUUSD", 7)
        self.store.db.execute("INSERT INTO checkpoints VALUES(?,?,?)", (self.xau, 3, json.dumps(s)))
        self.store.db.commit()
        self.store.acquire(self.xau, self.lease)
        self.assertEqual(self.store.save(self.xau, self.lease, 2, 7, s), 3)
        self.reopen()
        self.assertEqual(self.store.save(self.xau, self.lease, 2, 7, s), 3)

    def test_identity_and_numeric_validation(self):
        self.store.acquire(self.xau, self.lease)
        s = state("RZXA1", 1, "XAUUSD", 1)
        with self.assertRaisesRegex(ValueError, "BASE_REVISION_INVALID"):
            self.store.save(self.xau, self.lease, False, 1, s)
        s["Symbol"] = "EURUSD"
        with self.assertRaisesRegex(ValueError, "STATE_ACCOUNT_SYMBOL_INVALID"):
            self.store.save(self.xau, self.lease, 0, 1, s)
        self.assertEqual(self.store.acquire(self.xau, self.lease), (0, None))

    def test_private_files(self):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        path = Path(self.folder.name) / "health.json"
        _write_snapshot(path, {"execution_authority": "NONE"})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(path.read_text()), {"execution_authority": "NONE"})


if __name__ == "__main__":
    unittest.main()
