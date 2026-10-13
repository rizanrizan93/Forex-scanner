"""Remote, bridge-only deployment. Preserve local changes and checkpoint identity."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

ROOT = Path('/home/Rizanrizan/Forex-scanner')
UNIT = 'rizan-cbot-bridge.service'
PRODUCTION = ('server.py', 'feeds.py', 'timestamps.py', 'repair_legacy_xau_timestamps.py')
MODEL_HASH = '7ab0cd24eb2e46480d0ba371ba2cd713c5d6bd30747aee71f91ced5a57fce8bf'
MODELS = {'XAU_BATCH_STAGE_FIXED_REF_WAL_V1', 'XAU_BATCH_SEND_REF_COOLDOWN_V1'}
ALLOWED_PATCH = {f'cbot_bridge/{name}' for name in (*PRODUCTION, 'test_protocol.py', 'test_session_soak.py', 'test_timestamps.py')}


def command(args, *, cwd=ROOT, env=None, timeout=60, check=True):
    result = subprocess.run(args, cwd=cwd, env=env, timeout=timeout,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and result.returncode:
        raise RuntimeError('COMMAND_FAILED:' + Path(args[0]).name)
    return result


def prop(name):
    return command(['systemctl', 'show', UNIT, '--value', '-p', name]).stdout.strip()


def parse_env(text):
    result = {}
    for line in text.splitlines():
        if line.lstrip().startswith('#') or '=' not in line:
            continue
        key, value = line.partition('=')[::2]
        key = key.strip().removeprefix('export ')
        if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
            result[key] = value.strip().strip('"\'')
    return result


def candidate(root, destination, patch):
    destination.mkdir(mode=0o700)
    bridge = destination / 'cbot_bridge'
    bridge.mkdir(mode=0o700)
    for path in (root / 'cbot_bridge').glob('*.py'):
        shutil.copyfile(path, bridge / path.name)
    fixtures = patch.with_name('test-fixtures.json')
    if fixtures.is_file():
        supplied = json.loads(fixtures.read_text())
        if not set(supplied).issubset({'selftest.py', 'test_durable.py'}):
            raise RuntimeError('TEST_FIXTURE_SCOPE_INVALID')
        for name, source in supplied.items():
            # Pinned regression inputs only in the candidate; local tests stay intact.
            (bridge / name).write_text(source)
    paths = set(re.findall(r'^diff --git a/(\S+) b/\S+$', patch.read_text(), re.M))
    if not paths or not paths.issubset(ALLOWED_PATCH):
        raise RuntimeError('PATCH_SCOPE_INVALID')
    args = ['git', 'apply', '--check', str(patch)]
    if command(args, cwd=destination, check=False).returncode == 0:
        command(['git', 'apply', str(patch)], cwd=destination)
        return 'PATCH_APPLIED_TO_CANDIDATE'
    if command(['git', 'apply', '--reverse', '--check', str(patch)], cwd=destination, check=False).returncode == 0:
        return 'PATCH_ALREADY_PRESENT'
    # Merge partial fixes in the private candidate using verified original blobs.
    base_file = patch.with_name('patch-bases.json')
    if not base_file.is_file():
        raise RuntimeError('LOCAL_BRIDGE_PATCH_CONFLICT_NO_CHANGE')
    bases = json.loads(base_file.read_text())
    for block in re.split(r'(?=^diff --git )', patch.read_text(), flags=re.M):
        if not block.strip():
            continue
        path = re.search(r'^diff --git a/(\S+) b/\S+', block, re.M)[1]
        target = destination / path
        with tempfile.TemporaryDirectory(prefix='bridge-merge-') as folder:
            work = Path(folder)
            part = work / 'part.patch'
            part.write_text(block)
            if command(['git', 'apply', '--reverse', '--check', str(part)], cwd=destination, check=False).returncode == 0:
                continue
            old_hash = re.search(r'^index ([a-f0-9]+)\.\.', block, re.M)[1]
            if set(old_hash) == {'0'}:
                if command(['git', 'apply', '--check', str(part)], cwd=destination, check=False).returncode:
                    raise RuntimeError('LOCAL_BRIDGE_PATCH_CONFLICT_NO_CHANGE:' + target.name)
                command(['git', 'apply', str(part)], cwd=destination)
                continue
            base = bases.get(path)
            if base is None:
                raise RuntimeError('LOCAL_BRIDGE_PATCH_CONFLICT_NO_CHANGE:' + target.name)
            raw = base.encode()
            digest = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
            if not digest.startswith(old_hash):
                raise RuntimeError('PATCH_BASE_HASH_INVALID')
            upstream = work / path
            upstream.parent.mkdir(parents=True)
            upstream.write_text(base)
            command(['git', 'apply', str(part)], cwd=work)
            if not target.exists() and target.name.startswith('test_'):
                # Older VPS checkouts may lack the regression fixture. It is
                # created only in this candidate and is never deployed.
                shutil.copyfile(upstream, target)
                continue
            original = work / 'original'
            original.write_text(base)
            merged = command(['git', 'merge-file', '-p', str(target), str(original), str(upstream)], cwd=work, check=False)
            if merged.returncode:
                raise RuntimeError('LOCAL_BRIDGE_PATCH_CONFLICT_NO_CHANGE:' + target.name)
            target.write_text(merged.stdout)
    return 'PATCH_THREE_WAY_MERGED_LOCAL_CHANGES_PRESERVED'


def atomic_copy(source, target):
    temporary = target.with_name(target.name + '.deploy-new')
    shutil.copyfile(source, temporary)
    temporary.chmod(0o600)
    os.replace(temporary, target)


def run(mode, patch, release_sha):
    if not re.fullmatch(r'[a-f0-9]{40}', release_sha):
        raise RuntimeError('RELEASE_SHA_INVALID')
    if ROOT.is_symlink() or Path.home() != ROOT.parent:
        raise RuntimeError('RUNNER_USER_OR_REPO_INVALID')
    python = ROOT / '.venv/bin/python'
    if not python.is_file() or prop('WorkingDirectory') != str(ROOT):
        raise RuntimeError('VPS_LAYOUT_INVALID')
    start = prop('ExecStart')
    if str(python) not in start or str(ROOT / 'cbot_bridge/server.py') not in start:
        raise RuntimeError('UNEXPECTED_BRIDGE_EXECSTART')
    environment = {}
    for setting in shlex.split(prop('Environment')):
        key, separator, value = setting.partition('=')
        if separator:
            environment[key] = value
    # systemd EnvironmentFile settings override Environment settings.
    for path in re.findall(r'(\S+) \(ignore_errors=(?:yes|no)\)', prop('EnvironmentFiles')):
        file = Path(path)
        if not file.is_file() or file.is_symlink():
            raise RuntimeError('ENV_FILE_INVALID')
        environment.update(parse_env(file.read_text()))
    if len(environment.get('RIZAN_BRIDGE_TOKEN', '')) < 32:
        raise RuntimeError('EXISTING_BRIDGE_TOKEN_UNAVAILABLE')
    database = Path(environment.get('RIZAN_STATE_DB', 'state/rizan-checkpoints.sqlite'))
    if not database.is_absolute():
        database = ROOT / database
    if not database.is_file() or database.is_symlink():
        raise RuntimeError('EXISTING_STATE_DATABASE_NOT_FOUND')
    if command(['systemctl', 'is-active', '--quiet', UNIT], check=False).returncode:
        raise RuntimeError('BRIDGE_NOT_ACTIVE_BEFORE_DEPLOY')
    command(['sudo', '-n', 'true'])
    scratch = Path(tempfile.mkdtemp(prefix='rizan-bridge-candidate-'))
    try:
        result = candidate(ROOT, scratch / 'candidate', patch)
        runtime = {**os.environ, **environment}
        runtime['PYTHONPATH'] = str(ROOT / 'src')
        bridge = scratch / 'candidate/cbot_bridge'
        tests = command([str(python), '-m', 'unittest', 'discover', '-s', str(bridge), '-p', 'test_*.py'], cwd=scratch / 'candidate', env=runtime, timeout=180, check=False)
        if tests.returncode:
            # Report diagnostic identifiers only, never exception values or state.
            for name in re.findall(r"ModuleNotFoundError: No module named '([A-Za-z0-9_.]+)'", tests.stderr):
                print('CANDIDATE_MISSING_MODULE:' + name, flush=True)
            for kind, name in re.findall(r'^(FAIL|ERROR): ([A-Za-z0-9_.]+)', tests.stderr, re.M):
                print('CANDIDATE_TEST_' + kind + ':' + name, flush=True)
            for file, line in re.findall(r'File "([^"]+)", line (\d+)', tests.stderr):
                name = Path(file).name
                if re.fullmatch(r'[A-Za-z0-9_.-]+', name):
                    print('CANDIDATE_TEST_FRAME:' + name + ':' + line, flush=True)
            for value in re.findall(r'^AssertionError: (.{0,200})$', tests.stderr, re.M):
                if re.fullmatch(r"[A-Za-z0-9_ '!=<>.:-]+", value):
                    print('CANDIDATE_ASSERTION:' + value, flush=True)
            raise RuntimeError('CANDIDATE_TESTS_FAILED')
        print('CANDIDATE_TESTS_PASS ' + result, flush=True)
        if mode == 'audit':
            print('AUDIT_PASS_NO_SERVICE_OR_STATE_CHANGE', flush=True)
            return
        backup = ROOT / 'state' / ('bridge-backup-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()))
        backup.mkdir(mode=0o700)
        existing = {}
        for name in PRODUCTION:
            path = ROOT / 'cbot_bridge' / name
            existing[name] = path.exists()
            if path.exists():
                shutil.copyfile(path, backup / name)
                (backup / name).chmod(0o600)
        (backup / 'metadata.json').write_text(json.dumps({'unit': UNIT, 'release_sha': release_sha, 'existing': existing}))
        (backup / 'metadata.json').chmod(0o600)
        stopped = False
        database_backed_up = False
        service_start_attempted = False
        try:
            command(['sudo', '-n', 'systemctl', 'stop', UNIT])
            stopped = True
            if command(['systemctl', 'is-active', '--quiet', UNIT], check=False).returncode == 0:
                raise RuntimeError('BRIDGE_STOP_FAILED')
            source = sqlite3.connect(database)
            dest = sqlite3.connect(backup / 'checkpoints.sqlite')
            source.backup(dest)
            dest.close()
            (backup / 'checkpoints.sqlite').chmod(0o600)
            database_backed_up = True
            rows = source.execute('SELECT key,state FROM checkpoints').fetchall()
            source.close()
            repair_file = bridge / 'repair_legacy_xau_timestamps.py'
            count = 0
            for key, raw in rows:
                if not key.startswith('RZXA1:'):
                    continue
                state = json.loads(raw)
                model = state.get('ExecutionModel')
                if state.get('ContractHash') != MODEL_HASH or model not in MODELS:
                    raise RuntimeError('CHECKPOINT_SOURCE_PROVENANCE_UNCONFIRMED')
                command([str(python), str(repair_file), str(database), '--key', key,
                         '--execution-model', model, '--apply', '--confirm-legacy-utc-producer'], env=runtime)
                count += 1
            for name in PRODUCTION:
                atomic_copy(bridge / name, ROOT / 'cbot_bridge' / name)
            service_start_attempted = True
            command(['sudo', '-n', 'systemctl', 'start', UNIT])
            for _ in range(3):
                time.sleep(3)
                command(['systemctl', 'is-active', '--quiet', UNIT])
            # Synthetic identities only; never save a checkpoint or send an order.
            probe = '''import asyncio,json,os,uuid
from websockets.asyncio.client import connect
from timestamps import validate_timestamps
async def run():
 token=os.environ['RIZAN_BRIDGE_TOKEN']
 hello={'type':'hello','token':token,'key':'RZXA1:1:XAUUSD','lease':uuid.uuid4().hex,'contract':'7ab0cd24eb2e46480d0ba371ba2cd713c5d6bd30747aee71f91ced5a57fce8bf'}
 for cycle in range(2):
  async with connect('wss://rizan-bridge.duckdns.org:25345/',open_timeout=15) as ws:
   await ws.send(json.dumps(hello))
   ready=json.loads(await asyncio.wait_for(ws.recv(),15));assert ready['type']=='ready'
   snap=json.loads(await asyncio.wait_for(ws.recv(),20));assert snap['type']=='snapshot';validate_timestamps(snap)
   await ws.send('{"type":"ping"}')
   while True:
    pong=json.loads(await asyncio.wait_for(ws.recv(),15))
    if pong['type']=='snapshot':validate_timestamps(pong);continue
    assert pong['type']=='pong';validate_timestamps(pong);break
asyncio.run(run())
'''
            command([str(python), '-c', probe], cwd=ROOT / 'cbot_bridge', env=runtime, timeout=100)
            stopped = False
            manifest = {name: hashlib.sha256((ROOT / 'cbot_bridge' / name).read_bytes()).hexdigest() for name in PRODUCTION}
            (backup / 'deployed.json').write_text(json.dumps({'sha': release_sha, 'files': manifest}))
            print('DEPLOY_PASS unit=' + UNIT + ' sha=' + release_sha, flush=True)
            print('WSS_AUTH_TIMESTAMP_HEARTBEAT_RECONNECT_PASS synthetic_only no_orders no_checkpoint_save', flush=True)
            print('BACKUP_DIRECTORY=' + str(backup), flush=True)
        except Exception:
            if stopped:
                command(['sudo', '-n', 'systemctl', 'stop', UNIT], check=False)
                for name, present in existing.items():
                    target = ROOT / 'cbot_bridge' / name
                    if present:
                        atomic_copy(backup / name, target)
                    elif target.exists():
                        target.unlink()
                # Never rewind WAL after clients may have reconnected and saved state.
                if database_backed_up and not service_start_attempted:
                    src = sqlite3.connect(backup / 'checkpoints.sqlite')
                    dst = sqlite3.connect(database)
                    src.backup(dst)
                    dst.close();src.close()
                command(['sudo', '-n', 'systemctl', 'start', UNIT], check=False)
                print('ROLLBACK_TO_PREDEPLOY_BRIDGE_ATTEMPTED', flush=True)
            raise
    finally:
        shutil.rmtree(scratch)


if __name__ == '__main__':
    args = argparse.ArgumentParser()
    args.add_argument('--mode', choices=('audit', 'deploy'), default='audit')
    args.add_argument('--patch', type=Path, required=True)
    args.add_argument('--sha', required=True)
    options = args.parse_args()
    try:
        run(options.mode, options.patch.resolve(), options.sha)
    except Exception as exc:
        # Never dump environment, checkpoint bodies or exception messages from libraries.
        message = str(exc)
        code = message if re.fullmatch(r'[A-Z_]+(?::[A-Za-z0-9_.-]+)?', message) else type(exc).__name__
        print('DEPLOY_FAILED:' + code, flush=True)
        sys.exit(1)
