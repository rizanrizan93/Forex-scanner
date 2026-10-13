import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from timestamps import parse_utc, utc_text, validate_timestamps
from server import Store
from selftest import state

class TimestampTests(unittest.TestCase):
    def test_legacy_missing_model_repair_preserves_model_revision_and_lost_ack(self):
        import subprocess
        import sys
        import json
        import hashlib
        from repair_legacy_xau_timestamps import encoded
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.db'; store=Store(path); key='RZXA1:1:XAUUSD'; lease='a'*32
            store.acquire(key,lease); legacy=state('RZXA1',1,'XAUUSD',1)
            legacy.pop('ExecutionModel',None)
            legacy.update(LastSignalUtc='0001-01-01T00:00:00', LastRealExitUtc='0001-01-01T00:00:00',
                          XauDay='0001-01-01T00:00:00', Eur={'LastExitUtc':'0001-01-01T00:00:00'})
            aware=json.loads(json.dumps(legacy))
            for field in ('LastSignalUtc','LastRealExitUtc','XauDay'): aware[field]+='Z'
            aware['Eur']['LastExitUtc']+='Z'
            store.save(key,lease,0,1,aware)
            raw=encoded(legacy)
            with store.db:
                store.db.execute('UPDATE checkpoints SET state=? WHERE key=?',(raw,key))
                store.db.execute('UPDATE checkpoint_receipts SET digest=? WHERE key=?',
                                 (hashlib.sha256(raw.encode()).hexdigest(),key))
            tool=Path(__file__).with_name('repair_legacy_xau_timestamps.py')
            args=[sys.executable,str(tool),str(path),'--key',key,'--execution-model','XAU_LEGACY_CORE_V1']
            subprocess.run(args,check=True,capture_output=True)
            self.assertEqual(store.db.execute('SELECT state FROM checkpoints WHERE key=?',(key,)).fetchone()[0],raw)
            subprocess.run(args+['--apply','--confirm-legacy-utc-producer'],check=True,capture_output=True)
            version,repaired=store.acquire(key,lease)
            self.assertEqual(version,1); self.assertEqual(repaired,aware)
            self.assertNotIn('ExecutionModel',repaired)
            self.assertEqual(store.save(key,lease,0,1,aware),1)
            store.db.close()

    def test_offsets_normalize_to_same_utc(self):
        for suffix, hour in (("Z",13),("+00:00",13),("+07:00",20),("-05:00",8)):
            parsed = parse_utc(f"2026-10-12T{hour:02}:30:03.640{suffix}")
            self.assertEqual(parsed, datetime(2026,10,12,13,30,3,640000,tzinfo=timezone.utc))
            self.assertEqual(utc_text(parsed), "2026-10-12T13:30:03.640+00:00")
    def test_naive_and_bad_offset_rejected(self):
        for value in ("2026-10-12T13:30:03.640", "2026-10-12T13:30:03+25:00", "badZ", None):
            with self.assertRaises(ValueError): parse_utc(value)
        with self.assertRaisesRegex(ValueError,"TIMESTAMP_OFFSET_REQUIRED"):
            utc_text(datetime(2026,10,12))
    def test_all_nested_wire_fields(self):
        for field in ("timestamp","ts","event_time","generated_at","created_at","server_time",
                      "signal_time","bar_time","LastSignalUtc","AvailableUtc","XauDay"):
            validate_timestamps({"checkpoint":[{field:"2026-10-12T13:30:03Z"}]})
            with self.assertRaisesRegex(ValueError,"TIMESTAMP_OFFSET_REQUIRED"):
                validate_timestamps({"checkpoint":[{field:"2026-10-12T13:30:03"}]})
    def test_bad_save_preserves_checkpoint_across_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"state.db";store=Store(path);key="RZXA1:1:XAUUSD";lease="a"*32
            store.acquire(key,lease);s=state("RZXA1",1,"XAUUSD",1)
            s["LastSignalUtc"]="2026-10-12T13:30:03.640Z"
            store.save(key,lease,0,1,s)
            bad={**s,"Revision":2,"LastSignalUtc":"2026-10-12T13:31:03.640"}
            with self.assertRaisesRegex(ValueError,"TIMESTAMP_OFFSET_REQUIRED"):
                store.save(key,lease,1,2,bad)
            store.db.close();store=Store(path)
            self.assertEqual(store.acquire(key,lease),(1,s))
            self.assertEqual(store.save(key,lease,0,1,s),1) # lost ACK is idempotent
            store.db.close()

    def test_explicit_legacy_utc_repair_preserves_values(self):
        from repair_legacy_xau_timestamps import repair
        value={"LastSignalUtc":"2026-10-12T13:30:03.640","PendingLabel":"unchanged", "PendingChildren":10,
               "nested":{"AtUtc":"2026-10-12T20:30:03.640+07:00"},"Revision":15}
        self.assertEqual(repair(value),1)
        self.assertEqual(value["LastSignalUtc"],"2026-10-12T13:30:03.640Z")
        self.assertEqual(value["nested"]["AtUtc"],"2026-10-12T20:30:03.640+07:00")
        self.assertEqual(value["PendingChildren"],10)
        self.assertEqual(value["Revision"],15)
        validate_timestamps(value)
