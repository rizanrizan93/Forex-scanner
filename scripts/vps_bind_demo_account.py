"""Bind a unique token-granted DEMO account; output labels/status only."""
import contextlib
import io
import os
import re
import stat
import tempfile
from pathlib import Path

ROOT = Path('/home/Rizanrizan/Forex-scanner')

def main():
    from fx_scanner.execution.policy import load_execution_policy
    from fx_scanner.execution.ctrader_tokens import CTraderTokenStateStore
    from fx_scanner.execution.ctrader_session import CTraderOpenApiSession
    policy = load_execution_policy(ROOT)
    cfg = policy.ctrader
    if str(cfg.get('environment', '')).upper() != 'DEMO' or not cfg.get('require_demo'):
        raise RuntimeError('DEMO_POLICY_REQUIRED')
    token_store = CTraderTokenStateStore(os.environ[cfg['token_state_path_env']])
    tokens = token_store.load(fallback_access=os.environ[cfg['access_token_env']],
                              fallback_refresh=os.environ[cfg['refresh_token_env']])
    session = CTraderOpenApiSession(
        client_id=os.environ[cfg['client_id_env']],
        client_secret=os.environ[cfg['client_secret_env']],
        access_token=tokens.access_token, refresh_token=tokens.refresh_token,
        token_update_callback=token_store.save, account_id=None, environment='demo',
        request_timeout_seconds=10,
    )
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            accounts = session.granted_accounts()
        if len(accounts) != 2:
            print('ACCOUNT_COUNT_CHANGED', flush=True)
            return 2
        for label, account in zip(('A', 'B'), accounts):
            print('Account ' + label + ': ' + ('LIVE' if account.is_live else 'DEMO'), flush=True)
        demos = [a for a in accounts if not a.is_live]
        if len(demos) != 1:
            print('DEMO_SELECTION_AMBIGUOUS_ENV_NOT_CHANGED', flush=True)
            return 2
        chosen = demos[0]
        if chosen.ctid_trader_account_id <= 0:
            print('DEMO_ACCOUNT_INVALID', flush=True)
            return 2
        session.account_id = chosen.ctid_trader_account_id
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            session.connect()
            trader = session.trader()
        login = int(getattr(trader, 'traderLogin', 0) or chosen.trader_login)
        if login <= 0 or int(trader.ctidTraderAccountId) != chosen.ctid_trader_account_id:
            print('DEMO_IDENTITY_NOT_VERIFIED_ENV_NOT_CHANGED', flush=True)
            return 2
        print('DEMO_ACCOUNT_AUTH_PASS', flush=True)
        print('GRANT_LOGIN_PRESENT' if chosen.trader_login > 0 else 'GRANT_LOGIN_OMITTED', flush=True)
        values = {
            'CTRADER_TRADER_LOGIN': str(login),
            'CTRADER_ACCOUNT_ID': str(chosen.ctid_trader_account_id),
            'FX_LIVE_TRADING_ENABLED': '0', 'FX_KILL_SWITCH': '1',
            'CTRADER_LIVE_AUTOTRADE_ENABLED': '0', 'CTRADER_DEMO_AUTOTRADE_ENABLED': '0',
        }
        target = ROOT / '.env'
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise RuntimeError('ENV_OWNER_OR_TYPE_INVALID')
            old = source.read()
        lines = []
        for line in old.splitlines():
            match = re.match(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=', line)
            if not match or match.group(1) not in values:
                lines.append(line)
        lines.extend(k + '=' + v for k, v in values.items())
        fd, temporary = tempfile.mkstemp(prefix='.env-bind-', dir=ROOT)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w') as output:
                output.write('\n'.join(lines) + '\n')
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        print('PRIVATE_DEMO_BINDING_UPDATED permission=600 live=disabled', flush=True)
        return 0
    finally:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            session.close()

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('DEMO_BIND_FAILED ' + type(exc).__name__, flush=True)
        raise SystemExit(1)
