#!/usr/bin/env bash
set -Eeuo pipefail

# RIZAN Forex Scanner - VPS bootstrap
# Safe scope: prepares the Linux environment, Python venv, project dependencies,
# and a short `cfx` command for opening Codex in this repository.
# It does NOT enable live trading, place orders, modify broker credentials,
# or print secret values.

log()  { printf '\n[SETUP] %s\n' "$*"; }
warn() { printf '\n[WARN] %s\n' "$*" >&2; }
fail() { printf '\n[ERROR] %s\n' "$*" >&2; exit 1; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
REPO_DIR="$SCRIPT_DIR"

[[ -d .git ]] || fail "Jalankan script ini dari clone repository Forex-scanner."

log "Repository: $REPO_DIR"
log "User: $(id -un) | Host: $(hostname)"

# ---- Base tools -----------------------------------------------------------
missing=()
for cmd in git curl python3; do
  command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
done

if ((${#missing[@]})); then
  warn "Tool dasar belum ada: ${missing[*]}"
  if command -v apt-get >/dev/null 2>&1; then
    log "Mencoba memasang paket dasar melalui apt. Sudo mungkin meminta password VPS."
    sudo apt-get update
    sudo apt-get install -y git curl python3 python3-venv python3-pip
  else
    fail "Package manager apt tidak tersedia. Install manual: git, curl, python3, python3-venv, python3-pip."
  fi
fi

# Python version contract from pyproject.toml: >=3.11,<3.15
python3 - <<'PY'
import sys
v = sys.version_info
if not ((3, 11) <= (v.major, v.minor) < (3, 15)):
    raise SystemExit(f"Python {v.major}.{v.minor} tidak didukung; butuh Python >=3.11,<3.15")
print(f"[OK] Python {v.major}.{v.minor}.{v.micro}")
PY

# ---- Virtual environment --------------------------------------------------
if [[ ! -d .venv ]]; then
  log "Membuat virtual environment .venv"
  if ! python3 -m venv .venv; then
    if command -v apt-get >/dev/null 2>&1; then
      log "python3-venv belum lengkap; mencoba memasangnya."
      sudo apt-get update
      sudo apt-get install -y python3-venv
      python3 -m venv .venv
    else
      fail "Gagal membuat .venv dan apt tidak tersedia."
    fi
  fi
else
  log ".venv sudah ada; menggunakan environment yang ada."
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel

log "Memasang dependency project + dev + dashboard + cTrader"
python -m pip install -e '.[dev,dashboard,ctrader]'

# ---- Local state directories ---------------------------------------------
mkdir -p state logs
chmod 700 state logs 2>/dev/null || true

# Never overwrite an existing .env. If absent, create only a local template copy.
if [[ ! -f .env && -f .env.example ]]; then
  cp .env.example .env
  chmod 600 .env
  log "Membuat .env dari .env.example. Isi secret tetap harus diisi secara lokal; script tidak menampilkan secret."
else
  log ".env tidak diubah."
fi

# ---- Codex discovery + persistent PATH -----------------------------------
CODEX_BIN="$(command -v codex 2>/dev/null || true)"
if [[ -z "$CODEX_BIN" && -x "$HOME/.local/bin/codex" ]]; then
  CODEX_BIN="$HOME/.local/bin/codex"
fi

if [[ -z "$CODEX_BIN" ]]; then
  warn "Codex CLI belum ditemukan. Login/install Codex harus diselesaikan terlebih dahulu."
else
  log "Codex ditemukan: $CODEX_BIN"
  "$CODEX_BIN" --version || true
fi

mkdir -p "$HOME/.local/bin"
PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
if [[ -f "$HOME/.bashrc" ]]; then
  grep -Fqx "$PATH_LINE" "$HOME/.bashrc" || printf '\n%s\n' "$PATH_LINE" >> "$HOME/.bashrc"
else
  printf '%s\n' "$PATH_LINE" > "$HOME/.bashrc"
fi

# ---- One-word launcher: cfx ----------------------------------------------
cat > "$HOME/.local/bin/cfx" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
REPO="$REPO_DIR"
cd "\$REPO"
if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi
CODEX_BIN="\$(command -v codex 2>/dev/null || true)"
if [[ -z "\$CODEX_BIN" && -x "\$HOME/.local/bin/codex" ]]; then
  CODEX_BIN="\$HOME/.local/bin/codex"
fi
if [[ -z "\$CODEX_BIN" ]]; then
  echo "Codex CLI tidak ditemukan."
  exit 1
fi
exec "\$CODEX_BIN" -C "\$REPO"
EOF
chmod 700 "$HOME/.local/bin/cfx"

# ---- Non-secret health summary -------------------------------------------
log "Sanity check project"
python - <<'PY'
import fx_scanner
print("[OK] import fx_scanner berhasil")
PY

printf '\n============================================================\n'
printf ' VPS BOOTSTRAP SELESAI\n'
printf '============================================================\n'
printf 'Repo      : %s\n' "$REPO_DIR"
printf 'Python    : %s\n' "$(python --version 2>&1)"
printf 'Venv      : %s/.venv\n' "$REPO_DIR"
printf 'Codex     : %s\n' "${CODEX_BIN:-BELUM DITEMUKAN}"
printf '\nMulai sekarang, untuk membuka Codex langsung di scanner cukup ketik:\n\n'
printf '    cfx\n\n'
printf 'Jika shell lama belum mengenali cfx, ketik sekali: source ~/.bashrc\n'
printf 'Script ini TIDAK mengaktifkan trading live dan TIDAK mengubah secret broker.\n'
printf '============================================================\n'
