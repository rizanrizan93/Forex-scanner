from __future__ import annotations

import os

import five_core_tournament_v1 as base


symbol = os.environ.get("CORE_SYMBOL", "").strip().upper()
if symbol not in base.SYMBOLS:
    raise SystemExit(f"CORE_SYMBOL must be one of {list(base.SYMBOLS)}; got {symbol!r}")

base.SYMBOLS = {symbol: base.SYMBOLS[symbol]}
base.main()
