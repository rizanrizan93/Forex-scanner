import unittest,hashlib
from pathlib import Path
R=Path(__file__).resolve().parent.parent
class SourceTransportOnly(unittest.TestCase):
 def test_transport_only_allowlist(self):
  original=R/'source_original_unchanged';patched=R/'source_patched_TRANSPORT_ONLY_UNBUILT'
  allowed={'PortfolioHost.cs','xau/RizanRobot.cs','eur/RizanRobot.cs'}
  for p in original.rglob('*'):
   if not p.is_file():continue
   rel=p.relative_to(original)
   q=patched/rel
   self.assertTrue(q.is_file())
   if rel.as_posix() not in allowed:self.assertEqual(p.read_bytes(),q.read_bytes(),str(rel))
 def test_repair_is_guarded_and_route_unique(self):
  patched=R/'source_patched_TRANSPORT_ONLY_UNBUILT'
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
