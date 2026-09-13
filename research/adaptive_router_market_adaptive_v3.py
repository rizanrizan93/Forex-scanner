from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from adaptive_router_public_backtest import SYMBOLS, fetch_daily, metrics
from adaptive_router_market_core_v2 import COST_R, generate_shadow

VERSION = "MARKET_ADAPTIVE_ROUTER_V3_HIERARCHICAL"


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


def score_candidate(c: dict[str, Any], history: list[dict[str, Any]], now: datetime) -> tuple[bool, float, str]:
    family = [x for x in history if x["setup"] == c["setup"] and datetime.fromisoformat(x["exit_at"]) >= now - timedelta(days=1825)][-120:]
    exact = [x for x in family if x["regime"] == c["regime"]][-60:]
    recent = [x for x in exact if datetime.fromisoformat(x["exit_at"]) >= now - timedelta(days=365)][-24:]
    symbol = [x for x in exact if x["symbol"] == c["symbol"]][-16:]
    F, E, R, S = stat(family), stat(exact), stat(recent), stat(symbol)
    if F["n"] < 30 or E["n"] < 16:
        return False, -999.0, "COLD_START"
    if F["exp"] <= 0 or F["pf"] <= 1.05:
        return False, -999.0, "FAMILY_VETO"
    if E["exp"] <= 0.03 or E["pf"] <= 1.08:
        return False, -999.0, "REGIME_VETO"
    if R["n"] >= 6 and (R["exp"] <= -0.02 or R["pf"] <= 0.98):
        return False, -999.0, "RECENT_VETO"
    if S["n"] >= 5 and (S["exp"] < -0.05 or S["pf"] < 0.90):
        return False, -999.0, "SYMBOL_VETO"
    recent_exp = R["exp"] if R["n"] >= 6 else E["exp"]
    symbol_exp = S["exp"] if S["n"] >= 5 else E["exp"]
    blended = 0.25 * F["exp"] + 0.35 * E["exp"] + 0.25 * recent_exp + 0.15 * symbol_exp
    penalty = 0.35 * E["sd"] / math.sqrt(max(E["n"], 1.0))
    score = blended - penalty
    if score <= 0.02:
        return False, score, "CONFIDENCE_VETO"
    return True, score, "PASS"


def run_router(shadow: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    shadow = sorted(shadow, key=lambda x: (x["signal_at"], x["symbol"], x["setup"]))
    by_exit = sorted(shadow, key=lambda x: x["exit_at"])
    history: list[dict[str, Any]] = []
    active_until: dict[str, datetime] = {}
    selected: list[dict[str, Any]] = []
    reasons: dict[str, int] = defaultdict(int)
    p = 0
    k = 0
    while k < len(shadow):
        signal_at = shadow[k]["signal_at"]
        now = datetime.fromisoformat(signal_at)
        while p < len(by_exit) and datetime.fromisoformat(by_exit[p]["exit_at"]) < now:
            history.append(by_exit[p]); p += 1
        group: list[dict[str, Any]] = []
        while k < len(shadow) and shadow[k]["signal_at"] == signal_at:
            group.append(shadow[k]); k += 1
        ranked: list[tuple[float, dict[str, Any]]] = []
        for c in group:
            if active_until.get(c["symbol"], datetime.min.replace(tzinfo=timezone.utc)) >= now:
                reasons["ACTIVE_SYMBOL"] += 1; continue
            ok, score, reason = score_candidate(c, history, now)
            if not ok:
                reasons[reason] += 1; continue
            ranked.append((score, c))
        ranked.sort(key=lambda x: x[0], reverse=True)
        for score, c in ranked[:2]:
            t = dict(c); t["adaptive_score"] = round(score, 6)
            selected.append(t)
            active_until[c["symbol"]] = datetime.fromisoformat(c["exit_at"])
            reasons["SELECTED"] += 1
    return selected, dict(reasons)


def panel(trades: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"full": metrics(trades), "periods": {}, "by_setup": {}, "by_symbol": {}, "recent_by_setup": {}, "recent_by_symbol": {}}
    for a, b in ((2012, 2018), (2019, 2022), (2023, 2026)):
        xs = [x for x in trades if a <= datetime.fromisoformat(x["entry_at"]).year <= b]
        out["periods"][f"{a}-{b}"] = metrics(xs)
    for s in sorted({x["setup"] for x in trades}):
        out["by_setup"][s] = metrics([x for x in trades if x["setup"] == s])
        out["recent_by_setup"][s] = metrics([x for x in trades if x["setup"] == s and datetime.fromisoformat(x["entry_at"]).year >= 2023])
    for s in sorted({x["symbol"] for x in trades}):
        out["by_symbol"][s] = metrics([x for x in trades if x["symbol"] == s])
        out["recent_by_symbol"][s] = metrics([x for x in trades if x["symbol"] == s and datetime.fromisoformat(x["entry_at"]).year >= 2023])
    return out


def main() -> None:
    shadow: list[dict[str, Any]] = []
    coverage: dict[str, Any] = {}
    errors: list[str] = []
    for symbol in SYMBOLS:
        try:
            rows, source = fetch_daily(symbol)
            xs = generate_shadow(symbol, rows)
            shadow.extend(xs)
            coverage[symbol] = {"rows": len(rows), "source": source, "first": rows[0]["dt"].isoformat(), "last": rows[-1]["dt"].isoformat()}
            print("DATA", symbol, source, len(rows), "shadow", len(xs))
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
    selected, reasons = run_router(shadow)
    result = {
        "research_only": True,
        "execution_influence": False,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "future_information_in_selector": False,
            "hierarchical_gates": ["family_5y", "regime_5y", "recent_1y", "symbol_veto", "confidence_penalty"],
            "cost_r": COST_R,
            "note": "Exploratory research; v3 thresholds were designed after observing v1/v2 and are not an untouched holdout.",
        },
        "coverage": coverage,
        "errors": errors,
        "shadow_candidates": len(shadow),
        "selection_reasons": reasons,
        "results": panel(selected),
        "selected": selected,
    }
    print("RESULT_JSON=" + json.dumps(result, separators=(",", ":"), default=str))
    f = result["results"]["full"]
    print("SUMMARY", "n=", f.get("trades"), "wr=", f.get("win_rate"), "net_r=", f.get("net_r"), "exp=", f.get("expectancy_r"), "pf=", f.get("profit_factor"), "ret=", f.get("total_return_pct_at_0_5pct_risk"), "dd=", f.get("max_drawdown_pct_at_0_5pct_risk"))
    for p, m in result["results"]["periods"].items():
        print("PERIOD", p, "n=", m.get("trades"), "net_r=", m.get("net_r"), "exp=", m.get("expectancy_r"), "pf=", m.get("profit_factor"))
    for s, m in result["results"]["recent_by_setup"].items():
        print("RECENT_SETUP", s, "n=", m.get("trades"), "net_r=", m.get("net_r"), "exp=", m.get("expectancy_r"), "pf=", m.get("profit_factor"))
    for s, m in result["results"]["recent_by_symbol"].items():
        print("RECENT_SYMBOL", s, "n=", m.get("trades"), "net_r=", m.get("net_r"), "exp=", m.get("expectancy_r"), "pf=", m.get("profit_factor"))


if __name__ == "__main__":
    main()
