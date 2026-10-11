#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
dotnet build RizanEUR/RizanEUR/RizanEUR.csproj -c Release
dotnet build RizanXAU/RizanXAU/RizanXAU.csproj -c Release
mkdir -p compiled
cp RizanEUR/RizanEUR/bin/Release/net6.0/RizanEUR.algo compiled/
cp RizanXAU/RizanXAU/bin/Release/net6.0/RizanXAU.algo compiled/
