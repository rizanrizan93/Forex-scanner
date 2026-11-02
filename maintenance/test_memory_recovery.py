import importlib.util,json,sqlite3,tempfile,time,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('recovery',Path(__file__).with_name('vps_memory_recovery.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class RecoveryGuards(unittest.TestCase):
 def test_idle_guards(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);now=time.time()
   def health(connected=0,age=1):
    from datetime import datetime,timezone
    (p/'health.json').write_text(json.dumps({'observed_utc':datetime.fromtimestamp(now-age,timezone.utc).isoformat(),'connected':connected}))
   with sqlite3.connect(p/'checkpoints.sqlite') as db:
    db.executescript('CREATE TABLE bridge_leases(expires_at REAL,touched_at REAL); CREATE TABLE checkpoints(state TEXT);')
    db.execute('INSERT INTO checkpoints VALUES(?)',(json.dumps({'Basket':None,'PendingChildren':0}),));db.commit()
   health();self.assertTrue(module.idle_evidence(p,now)['eligible'])
   health(connected=1);self.assertFalse(module.idle_evidence(p,now)['eligible'])
   health(age=100);self.assertFalse(module.idle_evidence(p,now)['eligible'])
   health()
   with sqlite3.connect(p/'checkpoints.sqlite') as db:db.execute('INSERT INTO bridge_leases VALUES(?,?)',(now+10,now-1))
   self.assertFalse(module.idle_evidence(p,now)['eligible'])
   with sqlite3.connect(p/'checkpoints.sqlite') as db:db.execute('DELETE FROM bridge_leases');db.execute('UPDATE checkpoints SET state=?',(json.dumps({'Basket':{'Side':1}}),))
   self.assertFalse(module.idle_evidence(p,now)['eligible'])
   with sqlite3.connect(p/'checkpoints.sqlite') as db:db.execute('UPDATE checkpoints SET state=?',(json.dumps({'Basket':None,'PendingChildren':1}),))
   self.assertFalse(module.idle_evidence(p,now)['eligible'])
 def test_missing_state_preserved(self):
  with tempfile.TemporaryDirectory() as tmp:self.assertFalse(module.idle_evidence(Path(tmp))['eligible'])
if __name__=='__main__':unittest.main()
