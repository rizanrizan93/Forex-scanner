"""V1 identity, freshness, sanitization and fail-closed execution checks."""
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fx_scanner.cbot_v1_dashboard import CONTRACT, PROFILE, PROFILE_HASH, ROLES, evaluate_snapshot, checklist
from scripts.read_bootstrap125_dashboard import CONTRACTS, checkpoint_role, sanitize, snapshot

NOW = datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc)
ACCOUNT = '1237903'


def fixtures():
    states, leases = [], []
    for role in ROLES:
        key = ({'BOOTSTRAP': 'TPBOOT:' + PROFILE_HASH, 'BTCUSD': 'TPBTC:' + PROFILE_HASH,
                'XAUUSD': 'TPX_b6014ae7', 'EURUSD': 'TPE_b6014ae7'}[role] + ':' + ACCOUNT + ':' + role)
        contract, schema, execution = CONTRACTS[role]
        state = dict(AccountNumber=int(ACCOUNT), Symbol=role, Schema=schema, ContractHash=contract,
                     Revision=7, ProfileHash=PROFILE_HASH, NativeProfileHash=PROFILE_HASH,
                     ExecutionModel=execution, SecretToken='DO_NOT_PUBLISH', OpenLabel='', Intent=None)
        if role == 'BOOTSTRAP':
            state.update(Phase='GROWTH', GraduationBalance=153.71, GraduatedUtc=NOW.isoformat())
        states.append((key, 9, json.dumps(state)))
        leases.append((key, NOW.timestamp() + 45, NOW.timestamp()))
    return states, leases


def sample():
    states, leases = fixtures()
    return dict(contract=CONTRACT, profile=PROFILE, profile_hash=PROFILE_HASH, account_suffix='7903',
                read_only=True, execution_authority=False, observed_at=NOW.isoformat(), service_active=True,
                bridge=dict(observed_at=NOW.isoformat(), profile_ok=True, btc_feed_status='READY', macro_snapshot_present=True),
                roles=sanitize(states, leases, now=NOW))


class V1DashboardTests(unittest.TestCase):
    def test_four_roles_single_instance_never_prove_order_or_signal(self):
        model = evaluate_snapshot(sample(), now=NOW)
        self.assertEqual(model['phase'], 'GROWTH')
        self.assertTrue(model['bridge_ready'])
        self.assertTrue(all(s.startswith('TERHUBUNG') for s in model['statuses'].values()))
        self.assertTrue(all('❓' in x['Status'] for x in checklist(model, 'EURUSD')[3:]))
        self.assertEqual(model['roles']['BOOTSTRAP']['checkpoint_version'], 9)
        self.assertEqual(model['roles']['BOOTSTRAP']['client_revision'], 7)

    def test_stale_and_future_cannot_show_connection_or_phase_as_current(self):
        for now in (NOW + timedelta(minutes=16), NOW - timedelta(seconds=10)):
            m = evaluate_snapshot(sample(), now=now)
            self.assertFalse(m['fresh'])
            self.assertFalse(m['bridge_ready'])
            self.assertEqual(m['phase'], 'UNKNOWN')
            self.assertEqual(set(m['statuses'].values()), {'STALE'})
            self.assertFalse(any(x['Status'].startswith('✅') for x in checklist(m, 'BTCUSD')))

    def test_bad_contract_legacy_account_and_duplicate_role_rejected(self):
        for key, value in [('contract', 'RIZAN_BUY050_READONLY_V1'), ('profile_hash', 'legacy'),
                           ('account_suffix', '4480'), ('execution_authority', True), ('read_only', False)]:
            p = sample(); p[key] = value
            with self.assertRaises(ValueError):
                evaluate_snapshot(p, now=NOW)
        p = sample(); p['roles'][0] = p['roles'][1]
        with self.assertRaises(ValueError):
            evaluate_snapshot(p, now=NOW)

    def test_expired_or_missing_lease_and_stale_health_are_unknown(self):
        p = sample(); p['roles'][1]['lease_expires_at'] = (NOW - timedelta(seconds=1)).isoformat()
        m = evaluate_snapshot(p, now=NOW)
        self.assertEqual(m['statuses']['XAUUSD'], 'KONEKSI BELUM TERVERIFIKASI')
        p = sample(); p['roles'][1]['lease_touched_at'] = None
        self.assertEqual(evaluate_snapshot(p, now=NOW)['statuses']['XAUUSD'], 'KONEKSI BELUM TERVERIFIKASI')
        p = sample(); p['bridge']['observed_at'] = (NOW - timedelta(minutes=3)).isoformat()
        self.assertFalse(evaluate_snapshot(p, now=NOW)['bridge_ready'])

    def test_fault_or_intent_is_never_a_fill(self):
        p = sample(); p['roles'][1]['fault'] = True; p['roles'][2]['pending_intent'] = True
        m = evaluate_snapshot(p, now=NOW)
        self.assertEqual(m['statuses']['XAUUSD'], 'TERBLOKIR')
        self.assertEqual(m['statuses']['EURUSD'], 'STATE AKTIF · CEK EKSEKUSI')
        self.assertTrue(checklist(m, 'EURUSD')[-1]['Status'].startswith('❓'))

    def test_legacy_and_probe_ignored_and_outputs_sanitized(self):
        states, leases = fixtures()
        states += [('TPX_13bfa137:' + ACCOUNT + ':XAUUSD', 99, '{}'),
                   ('TPPROBE:' + PROFILE_HASH + ':9000000000000000002:PROBE', 1, '{}')]
        rows = sanitize(states, leases, now=NOW)
        text = json.dumps(rows)
        self.assertEqual(len(rows), 4)
        for secret in (ACCOUNT, 'DO_NOT_PUBLISH', 'AccountNumber', 'OpenLabel'):
            self.assertNotIn(secret, text)
        self.assertIsNone(checkpoint_role('TPX_b6014ae7:1234480:XAUUSD'))
        self.assertIsNone(checkpoint_role('TPX_b6014ae7:' + ACCOUNT + ':EURUSD'))

    def test_invalid_state_identity_and_unknown_flags_not_assumed_healthy(self):
        states, leases = fixtures()
        state = json.loads(states[0][2]); state['GraduationBalance'] = 124
        states[0] = (states[0][0], 1, json.dumps(state))
        rows = sanitize(states, leases, now=NOW)
        self.assertFalse(rows[0]['identity_ok'])
        self.assertIsNone(rows[0]['fault'])
        p = sample(); p['roles'] = rows
        self.assertEqual(evaluate_snapshot(p, now=NOW)['phase'], 'UNKNOWN')

    def test_ambiguous_account_rejected(self):
        states, leases = fixtures()
        states.append((states[0][0].replace(ACCOUNT, '4567903'), 1, states[0][2]))
        with self.assertRaises(ValueError):
            sanitize(states, leases, now=NOW)

    def test_checklist_distinguishes_failed_guards_from_missing_candle_data(self):
        p = sample()
        p['roles'][0].update(fault=False, halted=False, phase='SEED')
        p['roles'][1]['quarantined'] = True
        m = evaluate_snapshot(p, now=NOW)
        rows = {r['Syarat']: r['Status'] for r in checklist(m, 'XAUUSD')}
        self.assertTrue(rows['Fase mengizinkan instrumen ini'].startswith('❌'))
        self.assertTrue(rows['Pengelola fase bebas fault/halt'].startswith('✅'))
        self.assertTrue(rows['Engine instrumen bebas fault/quarantine/exit pending'].startswith('❌'))
        self.assertTrue(rows['Candle tertutup dan warmup indikator lengkap'].startswith('❓'))
        self.assertFalse(any(r['Status'].startswith(('✅','❌')) for r in checklist(None, 'EURUSD')))

    def test_btc_weekend_and_bridge_feed_checked_separately_from_terminal(self):
        p = sample()
        p['roles'][3]['weekend_lock_until'] = (NOW + timedelta(hours=1)).isoformat()
        m = evaluate_snapshot(p, now=NOW)
        rows = {r['Syarat']: r['Status'] for r in checklist(m, 'BTCUSD')}
        self.assertTrue(rows['Feed BTC tersedia di bridge'].startswith('✅'))
        self.assertTrue(rows['Guard akhir pekan mengizinkan entry'].startswith('❌'))
        self.assertTrue(rows['PortfolioReady dan penerimaan feed terminal siap'].startswith('❓'))
        m = evaluate_snapshot(p, now=NOW + timedelta(minutes=16))
        self.assertTrue(all(r['Status'].startswith('❓') for r in checklist(m, 'BTCUSD')))

    def test_reader_opens_sqlite_without_modifying_checkpoint_or_lease(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dbpath = root / 'checkpoints.sqlite'
            states, leases = fixtures()
            with sqlite3.connect(dbpath) as db:
                db.execute('CREATE TABLE checkpoints(key TEXT,version INTEGER,state TEXT)')
                db.execute('CREATE TABLE bridge_leases(key TEXT,expires_at REAL,touched_at REAL)')
                db.executemany('INSERT INTO checkpoints VALUES(?,?,?)', states)
                db.executemany('INSERT INTO bridge_leases VALUES(?,?,?)', leases)
            original = dbpath.read_bytes()
            root.joinpath('health.json').write_text(json.dumps({'observed_utc': NOW.isoformat(), 'profile': PROFILE, 'btc': 'ready'}))
            with patch('scripts.read_bootstrap125_dashboard.subprocess.run') as run:
                run.return_value.returncode = 0; run.return_value.stdout = 'active\n'
                result = snapshot(root)
            self.assertEqual(original, dbpath.read_bytes())
            self.assertEqual(len(result['roles']), 4)
            self.assertNotIn('DO_NOT_PUBLISH', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
