import unittest,hashlib,json
from pathlib import Path
R=Path(__file__).resolve().parent.parent
class SourceTransportOnly(unittest.TestCase):
    def test_transport_only_allowlist(self):
        manifest=json.loads((R/'MANIFEST.json').read_text())
        allowed={'PortfolioHost.cs','xau/RizanRobot.cs','eur/RizanRobot.cs'}
        pinned=manifest['original_source_sha256']
        actual={p.relative_to(R/'source').as_posix() for p in (R/'source').rglob('*') if p.is_file()}
        expected={p.removeprefix('source/') for p in pinned}
        self.assertEqual(actual,expected)
        for ref,sha in pinned.items():
            rel=ref.removeprefix('source/')
            digest=hashlib.sha256((R/'source'/rel).read_bytes()).hexdigest()
            if rel in allowed:self.assertNotEqual(digest,sha,rel)
            else:self.assertEqual(digest,sha,rel)
    def test_repair_is_guarded_and_route_unique(self):
        patched=R/'source'
        s=(patched/'PortfolioHost.cs').read_text()
        self.assertIn('25345/buy050/',s)
        self.assertNotIn('25345/disp1506/',s)
        for sym in ['xau','eur']:
            s=(patched/sym/'RizanRobot.cs').read_text()
            self.assertIn('"BRIDGE_IDENTITY_INVALID"',s)
            self.assertIn('Owned.Length==0',s)
            self.assertIn('_state.PendingChildren==0',s)
            self.assertIn('_state.Basket==null',s)
if __name__=='__main__':unittest.main()
