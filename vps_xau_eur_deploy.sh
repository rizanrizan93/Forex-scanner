#!/usr/bin/env bash
set -Eeuo pipefail

# One-command VPS deployment for the frozen XAU/EUR research/runtime support.
# It installs the cBot bridge and the cTrader research feed as restartable services.
# It NEVER enables live trading, never changes broker credentials, and fails closed
# if the committed broker policy is not DISABLED + cTrader DEMO.

log(){ printf '\n[DEPLOY] %s\n' "$*"; }
warn(){ printf '\n[WARN] %s\n' "$*" >&2; }
fail(){ printf '\n[FAIL] %s\n' "$*" >&2; exit 2; }

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
[[ -d .git ]] || fail "Repository .git tidak ditemukan."

log "Menyiapkan dependency VPS"
bash "$ROOT/vps_setup.sh"
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
python -m pip install -r "$ROOT/cbot_bridge/requirements.txt"
python -m pip check

log "Memastikan execution policy tetap fail-closed"
python - <<'PY'
from pathlib import Path
import yaml
p=yaml.safe_load(Path('config/execution.yaml').read_text())
if str(p.get('mode','')).upper() != 'DISABLED':
    raise SystemExit('POLICY_NOT_DISABLED')
ct=p.get('ctrader') or {}
if str(ct.get('environment','')).upper() != 'DEMO' or ct.get('require_demo') is not True:
    raise SystemExit('CTRADER_NOT_DEMO_LOCKED')
print('POLICY_OK mode=DISABLED ctrader=DEMO require_demo=true')
PY

log "Audit kontrak frozen dan cBot"
python "$ROOT/scripts/audit_frozen_cbot_parity.py"

mkdir -p "$ROOT/state" "$ROOT/logs" "$ROOT/state/systemd"
chmod 700 "$ROOT/state" "$ROOT/logs" "$ROOT/state/systemd" 2>/dev/null || true

# Read simple KEY=VALUE settings without executing .env as shell code.
read_env(){
  local name="$1" file="${2:-$ROOT/.env}"
  [[ -f "$file" ]] || return 0
  python - "$name" "$file" <<'PY'
import sys
name,path=sys.argv[1:]
value=''
for raw in open(path, encoding='utf-8'):
    line=raw.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    k,v=line.split('=',1)
    if k.strip()!=name: continue
    v=v.strip()
    if len(v)>=2 and v[0]==v[-1] and v[0] in "'\"": v=v[1:-1]
    value=v
print(value,end='')
PY
}

secret_ok(){
  local v="$1"
  [[ -n "$v" && "$v" != *REPLACE* && "$v" != *YOUR_* && "$v" != *CHANGE_ME* ]]
}

BRIDGE_TOKEN="$(read_env RIZAN_BRIDGE_TOKEN)"
if [[ ${#BRIDGE_TOKEN} -lt 32 ]]; then
  BRIDGE_TOKEN="$(python - <<'PY'
import secrets
print(secrets.token_hex(24))
PY
)"
fi

HOST="$(read_env RIZAN_BRIDGE_HOST)"; HOST="${HOST:-127.0.0.1}"
CERT="$(read_env RIZAN_TLS_CERT)"
KEY="$(read_env RIZAN_TLS_KEY)"
PUBLIC_READY=0
if [[ "$HOST" != "127.0.0.1" && "$HOST" != "::1" && "$HOST" != "localhost" ]]; then
  if [[ -n "$CERT" && -n "$KEY" && -r "$CERT" && -r "$KEY" ]]; then
    PUBLIC_READY=1
  else
    warn "Host bridge publik diminta tetapi sertifikat/key TLS belum siap; bridge dipaksa localhost agar fail-closed."
    HOST="127.0.0.1"
  fi
fi

BRIDGE_ENV="$ROOT/state/cbot-bridge.env"
{
  printf 'RIZAN_BRIDGE_HOST=%s\n' "$HOST"
  printf 'RIZAN_BRIDGE_PORT=25345\n'
  printf 'RIZAN_BRIDGE_TOKEN=%s\n' "$BRIDGE_TOKEN"
  printf 'RIZAN_STATE_DB=%s\n' "$ROOT/state/rizan-checkpoints.sqlite"
  printf 'RIZAN_SNAPSHOT_PATH=%s\n' "$ROOT/state/xau_macro_event_snapshot.json"
  if (( PUBLIC_READY )); then
    printf 'RIZAN_TLS_CERT=%s\n' "$CERT"
    printf 'RIZAN_TLS_KEY=%s\n' "$KEY"
  fi
} > "$BRIDGE_ENV"
chmod 600 "$BRIDGE_ENV"

log "Menguji sumber macro/event XAU satu kali"
python "$ROOT/cbot_bridge/feeds.py" > "$ROOT/state/xau_macro_event_probe.json"
chmod 600 "$ROOT/state/xau_macro_event_probe.json"
if python - <<'PY'
import json
x=json.load(open('state/xau_macro_event_probe.json'))
ok=(x.get('Dgs10') is not None and x.get('Dfii10') is not None and x.get('ForexFactoryOk') is True and x.get('BlsOk') is True)
print('XAU_MACRO_EVENT_PROBE', 'PASS' if ok else 'FAIL_CLOSED', 'errors='+','.join(x.get('Errors') or []))
raise SystemExit(0 if ok else 3)
PY
then
  MACRO_OK=1
else
  MACRO_OK=0
  warn "Sumber macro/event belum lengkap saat probe. XAU akan memblokir entry baru sampai snapshot sehat."
fi

# Determine whether the continuous cTrader research worker has the required secrets.
RESEARCH_REQUIRED=(CTRADER_CLIENT_ID CTRADER_CLIENT_SECRET CTRADER_ACCESS_TOKEN CTRADER_REFRESH_TOKEN CTRADER_TRADER_LOGIN SUPABASE_URL SUPABASE_SECRET_KEY)
MISSING=()
for name in "${RESEARCH_REQUIRED[@]}"; do
  value="$(read_env "$name")"
  secret_ok "$value" || MISSING+=("$name")
done
RESEARCH_READY=1
if ((${#MISSING[@]})); then
  RESEARCH_READY=0
  warn "Research-cloud belum akan dijalankan; variable .env yang belum siap: ${MISSING[*]}"
fi

USER_NAME="$(id -un)"
BRIDGE_UNIT="$ROOT/state/systemd/rizan-cbot-bridge.service"
RESEARCH_UNIT="$ROOT/state/systemd/rizan-research-cloud.service"
cat > "$BRIDGE_UNIT" <<EOF
[Unit]
Description=RIZAN cBot frozen state + XAU macro/event bridge
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$ROOT
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=$BRIDGE_ENV
ExecStart=$ROOT/.venv/bin/python $ROOT/cbot_bridge/server.py
Restart=always
RestartSec=10
UMask=0077
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

cat > "$RESEARCH_UNIT" <<EOF
[Unit]
Description=RIZAN FP Markets cTrader research-cloud runtime
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$ROOT
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-$ROOT/.env
ExecStart=$ROOT/.venv/bin/python -m fx_scanner.cli research-cloud --heartbeat 8 --mtf-refresh 900
Restart=always
RestartSec=15
UMask=0077
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

log "Memasang service systemd 24/5 (sudo mungkin meminta password VPS satu kali)"
command -v sudo >/dev/null 2>&1 || fail "sudo tidak tersedia; service 24/5 belum dapat dipasang."
sudo install -m 0644 "$BRIDGE_UNIT" /etc/systemd/system/rizan-cbot-bridge.service
sudo install -m 0644 "$RESEARCH_UNIT" /etc/systemd/system/rizan-research-cloud.service
sudo systemctl daemon-reload
sudo systemctl enable rizan-cbot-bridge.service >/dev/null
sudo systemctl restart rizan-cbot-bridge.service
if (( RESEARCH_READY )); then
  sudo systemctl enable rizan-research-cloud.service >/dev/null
  sudo systemctl restart rizan-research-cloud.service
else
  sudo systemctl disable --now rizan-research-cloud.service >/dev/null 2>&1 || true
fi

sleep 2
BRIDGE_ACTIVE="$(sudo systemctl is-active rizan-cbot-bridge.service 2>/dev/null || true)"
RESEARCH_ACTIVE="$(sudo systemctl is-active rizan-research-cloud.service 2>/dev/null || true)"

if [[ "$BRIDGE_ACTIVE" != "active" ]]; then
  warn "Bridge service tidak active. Ringkasan log aman:"
  sudo journalctl -u rizan-cbot-bridge.service -n 20 --no-pager || true
fi
if (( RESEARCH_READY )) && [[ "$RESEARCH_ACTIVE" != "active" ]]; then
  warn "Research-cloud tidak active. Ringkasan log aman:"
  sudo journalctl -u rizan-research-cloud.service -n 20 --no-pager || true
fi

LISTEN="NO"
if command -v ss >/dev/null 2>&1 && ss -lnt 2>/dev/null | awk '{print $4}' | grep -Eq '(^|:)25345$'; then LISTEN="YES"; fi

printf '\n============================================================\n'
printf ' RIZAN XAU/EUR VPS DEPLOYMENT SUMMARY\n'
printf '============================================================\n'
printf 'Frozen parity            : PASS\n'
printf 'Broker execution policy  : DISABLED / cTrader DEMO\n'
printf 'XAU macro+event probe     : %s\n' "$([[ $MACRO_OK -eq 1 ]] && echo PASS || echo FAIL_CLOSED)"
printf 'cBot bridge service       : %s\n' "${BRIDGE_ACTIVE:-inactive}"
printf 'Port 25345 local listen   : %s\n' "$LISTEN"
printf 'Bridge remote WSS/TLS     : %s\n' "$([[ $PUBLIC_READY -eq 1 ]] && echo CONFIGURED_NOT_EXTERNALLY_VERIFIED || echo PENDING_TLS_DOMAIN_OR_CERT)"
printf 'Research credentials      : %s\n' "$([[ $RESEARCH_READY -eq 1 ]] && echo PRESENT || echo INCOMPLETE)"
printf 'cTrader research service  : %s\n' "${RESEARCH_ACTIVE:-inactive}"
printf 'Live auto trading         : NOT ENABLED\n'
printf 'Bridge token              : stored in state/cbot-bridge.env; value not printed\n'
printf 'Shared XAU snapshot       : state/xau_macro_event_snapshot.json\n'
printf '============================================================\n'

# Deployment itself is valid even if external TLS or credentials are pending;
# those states are explicitly reported and remain fail-closed.
