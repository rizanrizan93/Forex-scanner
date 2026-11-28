#!/usr/bin/env bash
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cd "$root"
p=research/fixed_basket_replication/native_baseline
test "$(git rev-parse HEAD:$p/original/native_replay)" = e8aa88fc892411818cd7cc7b59c09139671d8173
test "$(git rev-parse HEAD:$p/original/source)" = ac90373598cd758d508b87d209def40f7521a022
test "$(git hash-object "$p/native_v8_from_verified_original.patch")" = 6bd8efa56393512430f563da4b541a7e0f10cc5a
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir "$work/native"
cp -a "$p/original/." "$work/native/"
patch --batch --forward -d "$work/native" -p1 < "$p/native_v8_from_verified_original.patch"
mkdir -p "$root/recovery-build"
dotnet build "$work/native/native_replay/NovemberReplay.csproj" -c Release -o "$root/recovery-build" -p:DefineConstants=REPLAY --nologo
dotnet "$root/recovery-build/NovemberReplay.dll" --early-risk-selftest
(cd "$root/recovery-build"; sha256sum NovemberReplay.dll > SHA256SUMS)
printf '%s\n' '{"classification":"V8_NATIVE_BASELINE_BUILD_ONLY","r28Parity":false,"financialReplaysExecuted":0,"monteCarloExecuted":false,"algoBuilt":false,"liveApproved":false}' > "$root/recovery-build/STATUS.json"
