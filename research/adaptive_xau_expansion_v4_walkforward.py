from __future__ import annotations

import json
import math
import random
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from adaptive_router_public_backtest import fetch_daily, indicators, median_prior, metrics

VERSION = "XAU_EXPANSION_V4_PURGED_PARAMETER_WALKFORWARD"
SYMBOL = "XAUUSD"
SEED = 20260913
PURGE_DAYS = 31
BASE_COST_R = 0.05


@dataclass(frozen=True)
class ParamConfig:
    config_id: str
    signal_level: int
    risk_level: int
    trend_level: int
    hold_level: int
    tr_mult: float
    atr_mult: float
    adx_min: float
    body_atr_min: float
    lookback: int
    buffer_atr: float
    stop_atr: float
    rr: float
    trend_mode: int
    max_hold: int


def param_grid() -> list[ParamConfig]:
    signal = {
        0: (1.25, 1.10, 18.0, 0.40, 15, 0.00),
        1: (1.35, 1.18, 20.0, 0.50, 20, 0.03),
        2: (1.45, 1.25, 22.0, 0.60, 30, 0.05),
    }
    risk = {
        0: (1.00, 1.80),
        1: (1.10, 2.20),
        2: (1.25, 2.60),
    }
    hold = {0: 7, 1: 10, 2: 15}
    out: list[ParamConfig] = []
    for s in range(3):
        for r in range(3):
            for t in range(3):
                for h in range(3):
                    trm, atm, adx, body, lb, buf = signal[s]
                    stop, rr = risk[r]
                    out.append(
                        ParamConfig(
                            config_id=f"S{s}R{r}T{t}H{h}",
                            signal_level=s,
                            risk_level=r,
                            trend_level=t,
                            hold_level=h,
                            tr_mult=trm,
                            atr_mult=atm,
                            adx_min=adx,
                            body_atr_min=body,
                            lookback=lb,
                            buffer_atr=buf,
                            stop_atr=stop,
                            rr=rr,
                            trend_mode=t,
                            max_hold=hold[h],
                        )
                    )
    return out


def trend_ok(side: str, row: dict[str, Any], e20: float, e50: float, e200: float, mode: int) -> bool:
    if side == "LONG":
        if not e20 > e50:
            return False
        if mode >= 1 and not row["close"] > e20:
            return False
        if mode >= 2 and not e50 > e200:
            return False
    else:
        if not e20 < e50:
            return False
        if mode >= 1 and not row["close"] < e20:
            return False
        if mode >= 2 and not e50 < e200:
            return False
    return True


def generate_trades(rows: list[dict[str, Any]], cfg: ParamConfig) -> list[dict[str, Any]]:
    ind = indicators(rows)
    out: list[dict[str, Any]] = []
    i = 220
    while i < len(rows) - 2:
        r = rows[i]
        atr = ind["atr"][i]
        adx = ind["adx"][i]
        if not atr or atr <= 0 or adx is None:
            i += 1
            continue
        e20, e50, e200 = ind["e20"][i], ind["e50"][i], ind["e200"][i]
        med_atr = median_prior(ind["atr"], i, 50) or atr
        expansion = ind["tr"][i] >= cfg.tr_mult * atr or atr >= cfg.atr_mult * med_atr
        body = abs(r["close"] - r["open"])
        if not expansion or adx < cfg.adx_min or body < cfg.body_atr_min * atr or i < cfg.lookback:
            i += 1
            continue
        prev_hi = max(x["high"] for x in rows[i-cfg.lookback:i])
        prev_lo = min(x["low"] for x in rows[i-cfg.lookback:i])
        side = None
        if r["close"] > prev_hi + cfg.buffer_atr * atr and trend_ok("LONG", r, e20, e50, e200, cfg.trend_mode):
            side = "LONG"
        elif r["close"] < prev_lo - cfg.buffer_atr * atr and trend_ok("SHORT", r, e20, e50, e200, cfg.trend_mode):
            side = "SHORT"
        if side is None:
            i += 1
            continue

        entry_i = i + 1
        entry = float(rows[entry_i]["open"])
        risk = cfg.stop_atr * atr
        if risk <= 0 or risk / max(abs(entry), 1e-9) > 0.15:
            i += 1
            continue
        stop = entry - risk if side == "LONG" else entry + risk
        target = entry + cfg.rr * risk if side == "LONG" else entry - cfg.rr * risk
        last_i = min(len(rows) - 1, entry_i + cfg.max_hold)
        exit_i = last_i
        gross_r = None
        reason = "TIME"
        for j in range(entry_i, last_i + 1):
            b = rows[j]
            if side == "LONG":
                hit_sl = b["low"] <= stop
                hit_tp = b["high"] >= target
            else:
                hit_sl = b["high"] >= stop
                hit_tp = b["low"] <= target
            if hit_sl and hit_tp:
                gross_r = -1.0
                exit_i = j
                reason = "SL_AMBIGUOUS_FIRST"
                break
            if hit_sl:
                gross_r = -1.0
                exit_i = j
                reason = "SL"
                break
            if hit_tp:
                gross_r = cfg.rr
                exit_i = j
                reason = "TP"
                break
        if gross_r is None:
            px = float(rows[exit_i]["close"])
            gross_r = (px - entry) / risk if side == "LONG" else (entry - px) / risk
            gross_r = max(-1.5, min(cfg.rr, gross_r))
        out.append(
            {
                "symbol": SYMBOL,
                "timeframe": "D1",
                "setup": "EXPANSION_BREAKOUT",
                "side": side,
                "signal_at": rows[i]["dt"].isoformat(),
                "entry_at": rows[entry_i]["dt"].isoformat(),
                "exit_at": rows[exit_i]["dt"].isoformat(),
                "gross_r": round(gross_r, 6),
                "net_r": round(gross_r - BASE_COST_R, 6),
                "cost_r": BASE_COST_R,
                "exit_reason": reason,
                "param_config": cfg.config_id,
            }
        )
        i = exit_i + 1
    return out


def period(trades: list[dict[str, Any]], start: str | None, end: str) -> list[dict[str, Any]]:
    end_dt = datetime.fromisoformat(end + "T23:59:59+00:00")
    start_dt = None if start is None else datetime.fromisoformat(start + "T00:00:00+00:00")
    return [
        t for t in trades
        if (start_dt is None or datetime.fromisoformat(t["entry_at"]) >= start_dt)
        and datetime.fromisoformat(t["entry_at"]) <= end_dt
    ]


def reprice(trades: list[dict[str, Any]], cost_r: float) -> list[dict[str, Any]]:
    out = []
    for t in trades:
        x = dict(t)
        x["cost_r"] = cost_r
        x["net_r"] = round(float(t["gross_r"]) - cost_r, 6)
        out.append(x)
    return out


def bootstrap_positive_fraction(trades: list[dict[str, Any]], n: int = 1000) -> float:
    if not trades:
        return 0.0
    rs = [float(t["net_r"]) for t in trades]
    rng = random.Random(SEED + len(rs))
    return sum(sum(rng.choice(rs) for _ in rs) > 0 for _ in range(n)) / n


def q(trades: list[dict[str, Any]]) -> dict[str, Any]:
    m = metrics(trades)
    if not trades:
        return {"metrics": m, "bootstrap_positive_fraction": 0.0, "positive": False}
    b = bootstrap_positive_fraction(trades)
    n = int(m.get("trades", 0) or 0)
    exp = float(m.get("expectancy_r", 0.0) or 0.0)
    pf = float(m.get("profit_factor", 0.0) or 0.0)
    dd = float(m.get("max_drawdown_pct_at_0_5pct_risk", 0.0) or 0.0)
    positive = n >= 8 and exp >= 0.05 and pf >= 1.10 and b >= 0.60 and dd <= 12.0
    return {"metrics": m, "bootstrap_positive_fraction": round(b, 4), "positive": positive}


def is_neighbor(a: ParamConfig, b: ParamConfig) -> bool:
    d = (
        abs(a.signal_level - b.signal_level)
        + abs(a.risk_level - b.risk_level)
        + abs(a.trend_level - b.trend_level)
        + abs(a.hold_level - b.hold_level)
    )
    return d <= 1


def choose(configs: list[ParamConfig], streams: dict[str, list[dict[str, Any]]], train_end: str):
    train_q = {c.config_id: q(period(streams[c.config_id], None, train_end)) for c in configs}
    ranked = []
    for c in configs:
        own = train_q[c.config_id]
        if not own["positive"]:
            continue
        neigh = [x for x in configs if is_neighbor(c, x)]
        nq = [train_q[x.config_id] for x in neigh]
        support = sum(bool(x["positive"]) for x in nq) / len(nq)
        exps = [float(x["metrics"].get("expectancy_r", 0.0) or 0.0) for x in nq]
        pfs = [float(x["metrics"].get("profit_factor", 0.0) or 0.0) for x in nq]
        med_exp = statistics.median(exps)
        med_pf = statistics.median(pfs)
        if support < 0.40 or med_exp <= 0.0 or med_pf <= 1.0:
            continue
        m = own["metrics"]
        n = float(m.get("trades", 0) or 0)
        exp = float(m.get("expectancy_r", 0.0) or 0.0)
        pf = max(1e-9, float(m.get("profit_factor", 0.0) or 0.0))
        dd = float(m.get("max_drawdown_pct_at_0_5pct_risk", 0.0) or 0.0)
        boot = float(own["bootstrap_positive_fraction"])
        shrink = math.sqrt(n / (n + 12.0))
        score = (
            0.35 * med_exp + 0.30 * exp * shrink + 0.10 * math.log(min(pf, 5.0))
            + 0.10 * boot + 0.15 * support - 0.0125 * dd
        )
        ranked.append((score, c, {
            "score": round(score, 6),
            "support": round(support, 4),
            "neighbor_count": len(neigh),
            "neighbor_median_expectancy_r": round(med_exp, 6),
            "neighbor_median_profit_factor": round(med_pf, 4),
            "train_quality": own,
        }))
    if not ranked:
        return None, {
            "decision": "NO_TRADE_CONFIG",
            "positive_configs": sum(bool(x["positive"]) for x in train_q.values()),
            "config_count": len(configs),
        }
    ranked.sort(key=lambda z: (z[0], z[1].config_id), reverse=True)
    _, best, detail = ranked[0]
    detail = dict(detail)
    detail["decision"] = "SELECT_CONFIG"
    detail["selected_config"] = asdict(best)
    detail["positive_configs"] = sum(bool(x["positive"]) for x in train_q.values())
    detail["config_count"] = len(configs)
    return best, detail


def panel(trades: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "base_0_05R": metrics(reprice(trades, 0.05)),
        "stress_0_10R": metrics(reprice(trades, 0.10)),
        "severe_0_15R": metrics(reprice(trades, 0.15)),
    }


def main() -> None:
    rows, source = fetch_daily(SYMBOL)
    configs = param_grid()
    streams = {c.config_id: generate_trades(rows, c) for c in configs}
    folds = [
        ("F1", "2016-12-31", "2017-02-01", "2018-12-31"),
        ("F2", "2018-12-31", "2019-02-01", "2020-12-31"),
        ("F3", "2020-12-31", "2021-02-01", "2022-12-31"),
        ("F4", "2022-12-31", "2023-02-01", "2024-12-31"),
        ("F5", "2024-12-31", "2025-02-01", "2026-09-30"),
    ]
    oos: list[dict[str, Any]] = []
    fold_rows = []
    for fold_id, train_end, test_start, test_end in folds:
        chosen, selection = choose(configs, streams, train_end)
        if chosen is None:
            test = []
            chosen_id = "NO_TRADE"
        else:
            chosen_id = chosen.config_id
            test = period(streams[chosen_id], test_start, test_end)
            for t in test:
                x = dict(t)
                x["oos_fold"] = fold_id
                x["trained_through"] = train_end
                oos.append(x)
        fold_rows.append({
            "fold": fold_id,
            "train_end": train_end,
            "purge_days": PURGE_DAYS,
            "test_start": test_start,
            "test_end": test_end,
            "chosen_config": chosen_id,
            "selection": selection,
            "test": panel(test),
        })
        sm = fold_rows[-1]["test"]["stress_0_10R"]
        print("FOLD", fold_id, "cfg=", chosen_id, "n=", sm.get("trades"), "net_r=", sm.get("net_r"), "exp=", sm.get("expectancy_r"), "pf=", sm.get("profit_factor"))

    center = next(c for c in configs if c.config_id == "S1R1T1H1")
    center_oos = []
    for fold_id, _, test_start, test_end in folds:
        for t in period(streams[center.config_id], test_start, test_end):
            x = dict(t)
            x["oos_fold"] = fold_id
            center_oos.append(x)

    result = {
        "research_only": True,
        "execution_influence": False,
        "live_execution_enabled": False,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data": {"symbol": SYMBOL, "source": source, "rows": len(rows), "first": rows[0]["dt"].isoformat(), "last": rows[-1]["dt"].isoformat()},
        "method": {
            "parameter_grid_size": len(configs),
            "grid_axes": ["signal_strictness", "risk_geometry", "trend_filter", "max_hold"],
            "purge_days": PURGE_DAYS,
            "anchored_expanding_training": True,
            "future_information_in_selection": False,
            "cost_stress_r": [0.05, 0.10, 0.15],
            "same_bar_policy": "SL_FIRST",
            "note": "Parameters are a research-informed neighborhood around the V3 expansion rule; each fold chooses using only earlier data.",
        },
        "folds": fold_rows,
        "oos_results": panel(oos),
        "oos_trades": oos,
        "oos_trade_count": len(oos),
        "center_config_reference": {"config": asdict(center), "oos_results": panel(center_oos), "oos_trade_count": len(center_oos)},
        "stream_counts": {k: len(v) for k, v in streams.items()},
    }
    print("RESULT_JSON=" + json.dumps(result, separators=(",", ":"), default=str))
    for k, m in result["oos_results"].items():
        print("OOS", k, "n=", m.get("trades"), "wr=", m.get("win_rate"), "net_r=", m.get("net_r"), "exp=", m.get("expectancy_r"), "pf=", m.get("profit_factor"), "dd=", m.get("max_drawdown_pct_at_0_5pct_risk"))
    m = result["center_config_reference"]["oos_results"]["stress_0_10R"]
    print("CENTER_STRESS", "n=", m.get("trades"), "net_r=", m.get("net_r"), "exp=", m.get("expectancy_r"), "pf=", m.get("profit_factor"))


if __name__ == "__main__":
    main()
