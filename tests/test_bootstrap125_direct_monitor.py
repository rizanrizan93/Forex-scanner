"""Direct monitor fallback and deployment isolation regression checks."""
import ast
from pathlib import Path
import unittest
from unittest.mock import patch
from fx_scanner.cbot_v1_dashboard import DIRECT_URL, SNAPSHOT_URL, fetch_snapshot

ROOT=Path(__file__).resolve().parents[1]

class DirectMonitorTests(unittest.TestCase):
    def test_direct_status_is_checked_before_github_fallback(self):
        with patch('fx_scanner.cbot_v1_dashboard.fetch_json',side_effect=[OSError('offline'), {'safe':'fixture'}]) as read, patch('fx_scanner.cbot_v1_dashboard.evaluate_snapshot'):
            self.assertEqual(fetch_snapshot(1),{'safe':'fixture'})
            self.assertEqual([x.args[0] for x in read.call_args_list],[DIRECT_URL,SNAPSHOT_URL])

    def test_invalid_direct_contract_cannot_be_used_as_live(self):
        with patch('fx_scanner.cbot_v1_dashboard.fetch_json',return_value={'contract':'legacy'}) as read:
            with self.assertRaises(ValueError):fetch_snapshot(2)
            self.assertEqual(read.call_count,2)

    def test_broker_protocol_allowlist_excludes_all_mutations(self):
        source=(ROOT/'scripts/read_bootstrap125_broker.py').read_text()
        tree=ast.parse(source)
        cls=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='Reader')
        assignment=next(x for x in cls.body if isinstance(x,ast.Assign))
        allowed=ast.literal_eval(assignment.value.args[0])
        self.assertTrue({'ProtoOADealListReq','ProtoOAOrderListReq','ProtoOAGetTrendbarsReq'} <= allowed)
        self.assertFalse(any(any(term in name for term in ('NewOrder','Cancel','Amend','ClosePosition','RefreshToken')) for name in allowed))
        self.assertIn('READ_ONLY_PROTOCOL_GUARD',source)
        self.assertIn('ORDER_DISABLED',source)

    def test_status_route_does_not_expose_private_bridge_directory(self):
        source=(ROOT/'operations/bootstrap125_monitor/install.py').read_text()
        self.assertNotIn('alias /var/lib/rizan-bootstrap125-bridge',source)
        self.assertNotIn("['systemctl','restart',BRIDGE]",source)
        self.assertIn('before!=bridge_identity()',source)
        self.assertIn('nginx',' '.join(source.split()))

if __name__=='__main__':unittest.main()
