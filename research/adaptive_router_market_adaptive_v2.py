from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from adaptive_router_public_backtest import SYMBOLS, fetch_daily, metrics
from adaptive_router_market_core_v2 import COST_R, generate_shadow

VERSION = "MARKET_ADAPTIVE_ROUTER_V2"


def stat(xs: list[dict[str, Any]]) -> dict[str, float]:
    rs = [float(x["net_r"]) for x in xs]
    gp = sum(x for x in rs if x > 0)
    gl = abs(sum(x for x in rs if x <= 0))
    return {
        "n": float(len(rs)),
        "exp": statistics.mean(rs) if rs else 0.0,
        "pf": gp / gl if gl > 0 else 99.0,
        "sd": statistics.pstdev(rs) if len(rs) > 1 else 0.0,
    }


def adaptive_score(c: dict[str, Any], history: list[dict[str, Any]], now: datetime) -> tuple[bool, float, dict[str, Any]]:
    same = [x for x in history if x["setup"] == c["setup"] and x["regime"] == c["regime"]]
    long_cut = now - timedelta(days=1095)
    short_cut = now - timedelta(days=365)
    long_h = [x for x in same if datetime.fromisoformat(x["exit_at"]) >= long_cut][-60:]
    short_h = [x for x in same if datetime.fromisoformat(x["exit_at"]) >= short_cut][-24:]
    symbol_h = [x for x in long_h if x["symbol"] == c["symbol"]][-16:]
    L, S, Y = stat(long_h), stat(short_h), stat(symbol_h)
    if L["n"] < 18:
        return False, -999.0, {"reason": "COLD_START", "long": L, "short": S, "symbol": Y}
    recent_exp = S["exp"] if S["n"] >= 6 else L["exp"]
    recent_pf = S["pf"] if S["n"] >= 6 else L["pf"]
    blended = 0.65 * recent_exp + 0.35 * L["exp"]
    if Y["n"] >= 5:
        blended = 0.80 * blended + 0.20 * Y["exp"]
    uncertainty = 0.30 * (L["sd"] / math.sqrt(max(L["n"], 1.0)))
    score = blended - uncertainty
    eligible = L["pf"] > 1.02 and recent_pf > 1.05 and blended > 0.03 and score > -0.03
    return eligible, score, {
        "reason": "PASS" if eligible else "EDGE_GATE",
        "long": L, "short": S, "symbol": Y,
        "blended_exp": round(blended, 6), "score": round(score, 6),
    }


def run_router(shadow: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    shadow = sorted(shadow, key=lambda x: (x["signal_at"], x["symbol"], x["setup"]))
    by_exit = sorted(shadow, key=lambda x: x["exit_at"])
    history: list[dict[str, Any]] = []
    p = 0
    selected: list[dict[str, Any]] = []
    reasons: dict[str, int] = defaultdict(int)
    active_until: dict[str, datetime] = {}
    k = 0
    while k < len(shadow):
        signal_at = shadow[k]["signal_at"]
        now = datetime.fromisoformat(signal_at)
        while p < len(by_exit) and datetime.fromisoformat(by_exit[p]["exit_at"]) < now:
            history.append(by_exit[p]); p += 1
        group: list[dict[str, Any]] = []
        while k < len(shadow) and shadow[k]["signal_at"] == signal_at:
            group.append(shadow[k]); k += 1
        ranked: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
        for c in group:
            if active_until.get(c["symbol"], datetime.min.replace(tzinfo=timezone.utc)) >= now:
                reasons["ACTIVE_SYMBOL"] += 1
                continue
            ok, score, detail = adaptive_score(c, history, now)
            if not ok:
                reasons[str(detail["reason"])] += 1
                continue
            ranked.append((score, c, detail))
        ranked.sort(key=lambda x: x[0], reverse=True)
        for score, c, detail in ranked[:2]:
            t = dict(c)
            t["adaptive_score"] = round(score, 6)
            t["adaptive_detail"] = detail
            selected.append(t)
            active_until[c["symbol"]] = datetime.fromisoformat(c["exit_at"])
            reasons["SELECTED"] += 1
    return selected, dict(reasons)


def split_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"full": metrics(trades), "by_setup": {}, "by_regime": {}, "by_symbol": {}, "periods": {}}
    for s in sorted({x["setup"] for x in trades}):
        out["by_setup"][s] = metrics([x for x in trades if x["setup"] == s])
    for r in sorted({x["regime"] for x in trades}):
        out["by_regime"][r] = metrics([x for x in trades if x["regime"] == r])
    for s in sorted({x["symbol"] for x in trades}):
        out["by_symbol"][s] = metrics([x for x in trades if x["symbol"] == s])
    for a, b in ((2012, 2018), (2019, 2022), (2023, 2026)):
        xs = [x for x in trades if a <= datetime.fromisoformat(x["entry_at"]).year <= b]
        out["periods"][f"{a}-{b}"] = metrics(xs)
    return out


def main() -> None:
    daily: dict[str, list[dict[str, Any]]] = {}
    sources: dict[str, str] = {}
    shadow: list[dict[str, Any]] = []
    errors: list[str] = []
    for symbol in SYMBOLS:
        try:
            rows, source = fetch_daily(symbol)
            daily[symbol], sources[symbol] = rows, source
            xs = generate_shadow(symbol, rows)
            shadow.extend(xs)
            print("DATA", symbol, source, len(rows), "shadow", len(xs), rows[0]["dt"].date(), rows[-1]["dt"].date())
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
            print("FAIL", symbol, exc)
    selected, reasons = run_router(shadow)
    result = {
        "research_only": True,
        "execution_influence": False,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "online_only": True,
            "selector_future_information": False,
            "shadow_learning": "Only shadow candidates whose exits precede the current signal are visible to the selector.",
            "regimes": ["EXPANSION", "TREND", "RANGE", "TRANSITION"],
            "long_window_days": 1095,
            "short_window_days": 365,
            "min_long_samples": 18,
            "max_new_positions_per_signal_date": 2,
            "cost_r": COST_R,
            "important_note": "Exploratory v2. The design follows findings from v1, so this is not a pristine untouched holdout test.",
        },
        "coverage": {
            s: {"rows": len(r), "first": r[0]["dt"].isoformat(), "last": r[-1]["dt"].isoformat(), "source": sources[s]}
            for s, r in daily.items()
        },
        "errors": errors,
        "shadow_candidates": len(shadow),
        "selection_reasons": reasons,
        "results": split_metrics(selected),
        "sample_selected": selected[:30],
    }
    print("RESULT_JSON=" + json.dumps(result, separators=(",", ":"), default=str))
    f = result["results"]["full"]
    print("SUMMARY", "trades=", f.get("trades"), "wr=", f.get("win_rate"), "net_r=", f.get("net_r"), "exp=", f.get("expectancy_r"), "pf=", f.get("profit_factor"), "return=", f.get("total_return_pct_at_0_5pct_risk"), "dd=", f.get("max_drawdown_pct_at_0_5pct_risk"))
    for p, m in result["results"]["periods"].items():
        print("PERIOD", p, "n=", m.get("trades"), "net_r=", m.get("net_r"), "exp=", m.get("expectancy_r"), "pf=", m.get("profit_factor"))
    for s, m in result["results"]["by_setup"].items():
        print("SETUP", s, "n=", m.get("trades"), "net_r=", m.get("net_r"), "exp=", m.get("expectancy_r"), "pf=", m.get("profit_factor"))


if __name__ == "__main__":
    main()
