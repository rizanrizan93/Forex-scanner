"""Regression tests for read-only LIVE account selection and shared portfolio accounting."""
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from fx_scanner import live_account_readonly as live


def account(login: str, account_id: int, *, is_live: bool = True, scope: int = 1):
    return SimpleNamespace(
        trader_login=login,
        ctid_trader_account_id=account_id,
        is_live=is_live,
        permission_scope=scope,
        broker_title_short="Test Broker",
    )


class LiveSharedAccountMonitorTests(unittest.TestCase):
    def setUp(self):
        self.active = account("7903", 12349322)
        self.retired = account("4480", 12348358)

    def test_xau_and_eur_share_one_active_live_account(self):
        groups = live._group_mapped_accounts([self.retired, self.active])
        self.assertEqual(len(groups), 1)
        selected, symbols = groups[0]
        self.assertEqual(selected.ctid_trader_account_id, 12349322)
        self.assertEqual(symbols, ("XAUUSD", "EURUSD"))

    def test_mapping_fails_closed_without_active_live_grant(self):
        with self.assertRaisesRegex(RuntimeError, "XAUUSD LIVE mapping"):
            live._group_mapped_accounts([self.retired])

    def test_mapping_rejects_demo_grant(self):
        with self.assertRaisesRegex(RuntimeError, "XAUUSD LIVE mapping"):
            live._group_mapped_accounts([account("7903", 12349322, is_live=False)])

    def test_mapping_rejects_duplicate_live_grants(self):
        with self.assertRaisesRegex(RuntimeError, "matches=2"):
            live._group_mapped_accounts([self.active, self.active])

    def test_mapping_rejects_unsupported_scope(self):
        with self.assertRaisesRegex(RuntimeError, "unsupported cTrader permission"):
            live._group_mapped_accounts([account("7903", 12349322, scope=99)])

    def test_shared_account_is_read_only_snapshotted_once(self):
        payload = {
            "state": "LIVE_READ_ONLY_OK",
            "environment": "live",
            "trader_login_last4": "7903",
            "account_id_last4": "9322",
            "symbol_lanes": ["XAUUSD", "EURUSD"],
            "account_scope": "SHARED_ACCOUNT_TOTAL",
            "balance": 4.12,
            "equity": 4.12,
            "open_positions": 0,
            "pending_orders": 0,
            "execution_authority": "NONE",
        }
        env = {
            "CTRADER_CLIENT_ID": "fake",
            "CTRADER_CLIENT_SECRET": "fake",
            "CTRADER_ACCESS_TOKEN": "fake",
        }
        buffer = io.StringIO()
        with patch.dict(os.environ, env), patch.object(
            live, "_discover_accounts", return_value=(self.retired, self.active)
        ), patch.object(live, "_snapshot_account", return_value=payload) as snap:
            with redirect_stdout(buffer):
                live.main()
        self.assertEqual(snap.call_count, 1)
        self.assertEqual(snap.call_args.kwargs["symbol_lanes"], ("XAUUSD", "EURUSD"))
        lines = [json.loads(item) for item in buffer.getvalue().strip().splitlines()]
        self.assertEqual(lines[0]["configured_mapping"], {"XAUUSD": "7903", "EURUSD": "7903"})
        report = lines[-1]
        self.assertEqual(report["state"], "LIVE_SHARED_ACCOUNT_READ_ONLY_OK")
        self.assertEqual(report["unique_account_count"], 1)
        self.assertEqual(len(report["accounts"]), 1)
        self.assertEqual(sum(a["balance"] for a in report["accounts"]), 4.12)
        self.assertEqual(report["execution_authority"], "NONE")


if __name__ == "__main__":
    unittest.main()
