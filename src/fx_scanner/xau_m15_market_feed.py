"""Fail-closed loader for the independent broker XAU M15 forecast feed."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.request import Request, urlopen

from .xau_m15_macro_forecast import validate_fast_m15_snapshot

URL = ("https://raw.githubusercontent.com/rizanrizan93/Forex-scanner/"
       "xau-m15-market-snapshots/runtime/xau_m15_market.json")


def fetch_fast_m15(*, now=None):
    now = now or datetime.now(UTC)
    slot = int(now.timestamp() // 30)
    request = Request(URL + "?slot=" + str(slot),
                      headers={"Cache-Control": "no-cache",
                               "User-Agent": "RIZAN-M15-LIVE-Readonly"})
    with urlopen(request, timeout=6) as response:
        raw = response.read(20_001)
    if len(raw) > 20_000:
        raise ValueError("XAU_M15_SNAPSHOT_TOO_LARGE")
    return validate_fast_m15_snapshot(json.loads(raw), now=now)
