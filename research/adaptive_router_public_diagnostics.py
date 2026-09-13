from __future__ import annotations

import importlib.util
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("router", HERE / "adaptive_router_public_backtest.py")
router = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(router)


def show(label, trades):
    m = router.metrics(trades)
    print(
        "DIAG", label,
        "n=", m.get("trades"),
        "wr=", m.get("win_rate"),
        "net_r=", m.get("net_r"),
        "exp=", m.get("expectancy_r"),
        "pf=", m.get("profit_factor"),
        "dd=", m.get("max_drawdown_pct_at_0_5pct_risk"),
        "return=", m.get("total_return_pct_at_0_5pct_risk"),
    )


def run(cost_r: float):
    all_trades = []
    for symbol in router.SYMBOLS:
        rows, src = router.fetch_daily(symbol)
        ts = router.backtest_symbol(symbol, rows, "D1", cost_r)
        all_trades.extend(ts)
        print("SOURCE", symbol, src, len(rows), rows[0]["dt"].date(), rows[-1]["dt"].date())
    all_trades.sort(key=lambda x: x["entry_at"])
    exp = [t for t in all_trades if t["setup"] == "EXPANSION_BREAKOUT"]
    tag = f"COST_{cost_r:.2f}R"
    show(f"{tag}_EXPANSION_ALL", exp)
    show(f"{tag}_EXPANSION_FX_ONLY", [t for t in exp if t["symbol"] != "XAUUSD"])
    show(f"{tag}_EXPANSION_XAU_PROXY", [t for t in exp if t["symbol"] == "XAUUSD"])
    show(f"{tag}_EXPANSION_LONG", [t for t in exp if t["side"] == "LONG"])
    show(f"{tag}_EXPANSION_SHORT", [t for t in exp if t["side"] == "SHORT"])

    for a, b in ((2012, 2018), (2019, 2022), (2023, 2026)):
        show(
            f"{tag}_EXPANSION_PERIOD_{a}_{b}",
            [t for t in exp if a <= datetime.fromisoformat(t["entry_at"]).year <= b],
        )
    for symbol in sorted({t["symbol"] for t in exp}):
        show(f"{tag}_EXPANSION_SYMBOL_{symbol}", [t for t in exp if t["symbol"] == symbol])

    by_year = defaultdict(list)
    for t in exp:
        by_year[datetime.fromisoformat(t["entry_at"]).year].append(t)
    for year in sorted(by_year):
        show(f"{tag}_EXPANSION_YEAR_{year}", by_year[year])

    # Check whether simply removing the historically weak sweep family is enough.
    no_sweep = [t for t in all_trades if t["setup"] != "LIQUIDITY_SWEEP"]
    show(f"{tag}_ROUTER_WITHOUT_SWEEP", no_sweep)


if __name__ == "__main__":
    run(0.05)
    run(0.10)
