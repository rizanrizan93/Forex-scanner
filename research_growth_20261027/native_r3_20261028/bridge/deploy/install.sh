#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077
if [[ ${EUID} -ne 0 ]]; then echo 'Run as root on the intended VPS.' >&2; exit 1; fi
account=${1:-}
if [[ ! $account =~ ^[1-9][0-9]{0,18}$ ]]; then echo 'Usage: sudo bash deploy/install.sh FULL_ACCOUNT_NUMBER' >&2; exit 1; fi
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
target=/opt/rizan-r3-bridge
unit=rizan-r3-bridge.service
if [[ -e /etc/rizan-r3-bridge.env || -e /etc/systemd/system/$unit || -e $target ]]; then
  echo 'R3 installation already exists; preserve its token and checkpoint. No changes made.' >&2; exit 1
fi
python3 - <<'PY'
import socket
with socket.socket() as s:s.bind(('127.0.0.1',25347))
PY
command -v python3 >/dev/null
command -v systemctl >/dev/null
getent group rizan-r3 >/dev/null || groupadd --system rizan-r3
id -u rizan-r3 >/dev/null 2>&1 || useradd --system --gid rizan-r3 --home-dir /var/lib/rizan-r3-bridge --shell /usr/sbin/nologin rizan-r3
install -d -m 0755 "$target"
install -m 0644 "$source_dir/"*.py "$source_dir/requirements.txt" "$source_dir/BTC_SEED_PACKET.json" "$target/"
python3 -m venv "$target/.venv"
"$target/.venv/bin/python" -m pip install --disable-pip-version-check -r "$target/requirements.txt"
python3 - "$account" <<'PY'
import os,secrets,sys
account=sys.argv[1]
if int(account)>9223372036854775807:raise SystemExit('Invalid account')
path='/etc/rizan-r3-bridge.env'
with open(path,'x') as f:
 f.write('R3_HOST=127.0.0.1\nR3_PORT=25347\nR3_STATE_DIR=/var/lib/rizan-r3-bridge\nR3_BTC_SEED=/opt/rizan-r3-bridge/BTC_SEED_PACKET.json\nR3_ALLOWED_ACCOUNTS='+account+'\nR3_BRIDGE_TOKEN='+secrets.token_urlsafe(48)+'\n')
os.chmod(path,0o600)
PY
install -m 0644 "$source_dir/deploy/$unit" "/etc/systemd/system/$unit"
systemctl daemon-reload
systemctl enable --now "$unit"
systemctl is-active --quiet "$unit"
echo 'R3 backend installed on127.0.0.1:25347. Existing bridge services were not restarted.'
echo 'Public WSS routing remains to be configured using deploy/nginx-r3-locations.conf.'
echo 'Token is stored privately in /etc/rizan-r3-bridge.env. Do not post it in chat.'
