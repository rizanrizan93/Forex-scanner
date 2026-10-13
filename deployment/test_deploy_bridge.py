import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('bridge_deploy', Path(__file__).with_name('deploy_bridge.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
REPO = Path(__file__).resolve().parents[1]
PATCH = REPO / 'deployment/bridge-connectivity.patch'

class DeploymentTests(unittest.TestCase):
    def test_partial_fix_merges_without_losing_local_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'repo'
            bridge = root / 'cbot_bridge'
            bridge.mkdir(parents=True)
            for name in ('server.py', 'feeds.py', 'selftest.py', 'test_durable.py', 'test_protocol.py'):
                (bridge / name).write_bytes(subprocess.check_output(['git', 'show', 'a25ffbeb:cbot_bridge/' + name], cwd=REPO))
            server = bridge / 'server.py'
            # Earlier VPS fix overlaps the import hunk, but agrees with upstream.
            server.write_text(server.read_text().replace('import time\n', 'import time\nfrom datetime import datetime, timezone\n') + '\n# PRESERVE_LOCAL_FIX\n')
            out = Path(folder) / 'out'
            self.assertEqual(module.candidate(root, out, PATCH), 'PATCH_THREE_WAY_MERGED_LOCAL_CHANGES_PRESERVED')
            merged = (out / 'cbot_bridge/server.py').read_text()
            self.assertIn('PRESERVE_LOCAL_FIX', merged)
            self.assertIn('validate_timestamps(request)', merged)
            self.assertEqual(merged.count('\nfrom datetime import datetime, timezone\n'), 1)
            self.assertNotIn('<<<<<<<', merged)

    def test_mixed_already_patched_files_are_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'repo'
            bridge = root / 'cbot_bridge'
            bridge.mkdir(parents=True)
            for name in ('server.py', 'feeds.py', 'selftest.py', 'test_durable.py', 'test_protocol.py'):
                (bridge / name).write_bytes(subprocess.check_output(['git', 'show', 'a25ffbeb:cbot_bridge/' + name], cwd=REPO))
            (bridge / 'feeds.py').write_bytes((REPO / 'cbot_bridge/feeds.py').read_bytes())
            out = Path(folder) / 'out'
            self.assertEqual(module.candidate(root, out, PATCH), 'PATCH_THREE_WAY_MERGED_LOCAL_CHANGES_PRESERVED')
            self.assertEqual((out / 'cbot_bridge/feeds.py').read_bytes(), (REPO / 'cbot_bridge/feeds.py').read_bytes())

    def test_preserves_unrelated_local_modifications_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'repo'
            bridge = root / 'cbot_bridge'
            bridge.mkdir(parents=True)
            for name in ('server.py', 'feeds.py', 'selftest.py', 'test_durable.py', 'test_protocol.py'):
                data = subprocess.check_output(['git', 'show', 'a25ffbeb:cbot_bridge/' + name], cwd=REPO)
                (bridge / name).write_bytes(data)
            with (bridge / 'server.py').open('a') as stream:
                stream.write('\n# PRESERVE_VPS_LOCAL_CHANGE\n')
            (root / 'models.py').write_text('LOCAL_ORDER_SIDE_FIX_UNCHANGED')
            first = Path(folder) / 'first'
            self.assertEqual(module.candidate(root, first, PATCH), 'PATCH_APPLIED_TO_CANDIDATE')
            self.assertIn('PRESERVE_VPS_LOCAL_CHANGE', (first / 'cbot_bridge/server.py').read_text())
            self.assertEqual((root / 'models.py').read_text(), 'LOCAL_ORDER_SIDE_FIX_UNCHANGED')
            self.assertEqual(module.candidate(first, Path(folder) / 'second', PATCH), 'PATCH_ALREADY_PRESENT')
    def test_conflict_fails_before_changing_original(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'repo'
            bridge = root / 'cbot_bridge'
            bridge.mkdir(parents=True)
            original = 'LOCAL_INCOMPATIBLE_SERVER\n'
            (bridge / 'server.py').write_text(original)
            with self.assertRaisesRegex(RuntimeError, 'LOCAL_BRIDGE_PATCH_CONFLICT'):
                module.candidate(root, Path(folder) / 'candidate', PATCH)
            self.assertEqual((bridge / 'server.py').read_text(), original)
    def test_rejects_patch_outside_bridge(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'repo'
            (root / 'cbot_bridge').mkdir(parents=True)
            patch = Path(folder) / 'unsafe.patch'
            patch.write_text('diff --git a/config/execution.yaml b/config/execution.yaml\n')
            with self.assertRaisesRegex(RuntimeError, 'PATCH_SCOPE_INVALID'):
                module.candidate(root, Path(folder) / 'candidate', patch)
    def test_environment_parser_does_not_execute_shell(self):
        self.assertEqual(module.parse_env('X=$(touch /tmp/SHOULD_NOT_RUN)\n# ignore\nTOKEN="value"'),
                         {'X': '$(touch /tmp/SHOULD_NOT_RUN)', 'TOKEN': 'value'})

    def test_failed_probe_never_rewinds_checkpoint_after_service_restart(self):
        import json
        import sqlite3
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'repo'
            (root / 'cbot_bridge').mkdir(parents=True)
            (root / 'state').mkdir()
            (root / '.venv/bin').mkdir(parents=True)
            (root / '.venv/bin/python').touch()
            for name in module.PRODUCTION:
                (root / 'cbot_bridge' / name).write_text('OLD_' + name)
            db_path = root / 'state/rizan-checkpoints.sqlite'
            db = sqlite3.connect(db_path)
            db.execute('CREATE TABLE checkpoints(key TEXT,state TEXT)')
            db.execute('INSERT INTO checkpoints VALUES(?,?)', ('RZXA1:1:XAUUSD', json.dumps({'ContractHash': module.MODEL_HASH, 'ExecutionModel': 'XAU_BATCH_SEND_REF_COOLDOWN_V1', 'Revision': 1})))
            db.commit(); db.close()
            starts = 0
            def fake_command(args, **kwargs):
                nonlocal starts
                if args[:5] == ['sudo', '-n', 'systemctl', 'start', module.UNIT]:
                    starts += 1
                    if starts == 1:
                        conn = sqlite3.connect(db_path)
                        state = {'ContractHash': module.MODEL_HASH, 'ExecutionModel': 'XAU_BATCH_SEND_REF_COOLDOWN_V1', 'Revision': 2, 'LastSignalUtc': '2026-10-13T00:00:00Z'}
                        conn.execute('UPDATE checkpoints SET state=?', (json.dumps(state),))
                        conn.commit(); conn.close()
                if '-c' in args:
                    raise RuntimeError('TEST_PROBE_FAILED')
                if args[:2] == ['systemctl', 'is-active'] and kwargs.get('check') is False:
                    return subprocess.CompletedProcess(args, 1, '', '')
                return subprocess.CompletedProcess(args, 0, '', '')
            # Initial preflight must be active; the subsequent stop check inactive.
            active_calls = 0
            def dispatch(args, **kwargs):
                nonlocal active_calls
                if args[:2] == ['systemctl', 'is-active']:
                    active_calls += 1
                    if active_calls == 1:
                        return subprocess.CompletedProcess(args, 0, '', '')
                return fake_command(args, **kwargs)
            def fake_candidate(root_arg, destination, patch_arg):
                (destination / 'cbot_bridge').mkdir(parents=True)
                for name in module.PRODUCTION:
                    (destination / 'cbot_bridge' / name).write_text('NEW_' + name)
                return 'PATCH_APPLIED_TO_CANDIDATE'
            properties = {'WorkingDirectory': str(root),
                          'ExecStart': str(root / '.venv/bin/python') + ' ' + str(root / 'cbot_bridge/server.py'),
                          'Environment': 'RIZAN_BRIDGE_TOKEN=' + 'x' * 40,
                          'EnvironmentFiles': ''}
            with patch.object(module, 'ROOT', root), patch.object(Path, 'home', return_value=root.parent), \
                 patch.object(module, 'prop', side_effect=lambda name: properties[name]), \
                 patch.object(module, 'command', side_effect=dispatch), \
                 patch.object(module, 'candidate', side_effect=fake_candidate), \
                 patch.object(module.time, 'sleep'):
                with self.assertRaisesRegex(RuntimeError, 'TEST_PROBE_FAILED'):
                    module.run('deploy', PATCH, 'a' * 40)
            conn = sqlite3.connect(db_path)
            state = json.loads(conn.execute('SELECT state FROM checkpoints').fetchone()[0])
            conn.close()
            self.assertEqual(state['Revision'], 2)
            self.assertEqual(state['LastSignalUtc'], '2026-10-13T00:00:00Z')
            self.assertEqual((root / 'cbot_bridge/server.py').read_text(), 'OLD_server.py')
