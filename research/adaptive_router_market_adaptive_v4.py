from __future__ import annotations

import json
import math
import random
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from adaptive_router_public_backtest import SYMBOLS, fetch_daily, metrics
from adaptive_router_market_core_v2 import COST_R, generate_shadow

VERSION = "MARKET_ADAPTIVE_ROUTER_V4_PURGED_ANCHORED"
SEED = 20260913
PURGE_DAYS = 31


@dataclass(frozen=True)
class RouterConfig:
    config_id: str
    sample_level: int
    edge_level: int
    confidence_level: int
    min_family: int
    min_exact: int
    family_exp_min: float
    family_pf_min: float
    regime_exp_min: float
    regime_pf_min: float
    recent_exp_floor: float
    recent_pf_floor: float
    symbol_exp_floor: float
    symbol_pf_floor: float
    penalty_coeff: float
    score_min: float


def config_grid() -> list[RouterConfig]:
    sample = {
        0: (24, 12),
        1: (30, 16),
        2: (36, 20),
    }
    edge = {
        0: (-0.01, 1.02, 0.00, 1.03, -0.05, 0.95, -0.10, 0.85),
        1: (0.00, 1.05, 0.03, 1.08, -0.02, 0.98, -0.05, 0.90),
        2: (0.03, 1.08, 0.05, 1.12, 0.00, 1.00, 0.00, 0.95),
    }
    confidence = {
        0: (0.25, 0.00),
        1: (0.35, 0.02),
        2: (0.45, 0.05),
    }
    out: list[RouterConfig] = []
    for s in range(3):
        for e in range(3):
            for c in range(3):
                mf, me = sample[s]
                fe, fp, re, rp, rx, rpf, sx, spf = edge[e]
                penalty, score_min = confidence[c]
                out.append(
                    RouterConfig(
                        config_id=f"S{s}E{e}C{c}",
                        sample_level=s,
                        edge_level=e,
                        confidence_level=c,
                        min_family=mf,
                        min_exact=me,
                        family_exp_min=fe,
                        family_pf_min=fp,
                        regime_exp_min=re,
                        regime_pf_min=rp,
                        recent_exp_floor=rx,
                        recent_pf_floor=rpf,
                        symbol_exp_floor=sx,
                        symbol_pf_floor=spf,
                        penalty_coeff=penalty,
                        score_min=score_min,
                    )
                )
    return out


def stat(xs: list[dict[str, Any]]) -> dict[str, float]:
    rs = [float(x["net_r"]) for x in xs]
    gp = sum(x for x in rs if x > 0)
    gl = abs(sum(x for x in rs if x <= 0))
    return {
        "n": float(len(rs)),
        "exp": statistics.mean(rs) if rs else 0.0,
        "pf": gp / gl if gl > 0 else (99.0 if gp > 0 else 0.0),
        "sd": statistics.pstdev(rs) if len(rs) > 1 else 0.0,
    }


def score_candidate(
    c: dict[str, Any], history: list[dict[str, Any]], now: datetime, cfg: RouterConfig
) -> tuple[bool, float, str]:
    ts_5y = now.timestamp() - 1825 * 86400
    ts_1y = now.timestamp() - 365 * 86400
    family = [
        x for x in history
        if x["setup"] == c["setup"] and datetime.fromisoformat(x["exit_at"]).timestamp() >= ts_5y
    ][-120:]
    exact = [x for x in family if x["regime"] == c["regime"]][-60:]
    recent = [x for x in exact if datetime.fromisoformat(x["exit_at"]).timestamp() >= ts_1y][-24:]
    symbol = [x for x in exact if x["symbol"] == c["symbol"]][-16:]
    F, E, R, S = stat(family), stat(exact), stat(recent), stat(symbol)

    if F["n"] < cfg.min_family or E["n"] < cfg.min_exact:
        return False, -999.0, "COLD_START"
    if F["exp"] <= cfg.family_exp_min or F["pf"] <= cfg.family_pf_min:
        return False, -999.0, "FAMILY_VETO"
    if E["exp"] <= cfg.regime_exp_min or E["pf"] <= cfg.regime_pf_min:
        return False, -999.0, "REGIME_VETO"
    if R["n"] >= 6 and (R["exp"] <= cfg.recent_exp_floor or R["pf"] <= cfg.recent_pf_floor):
        return False, -999.0, "RECENT_VETO"
    if S["n"] >= 5 and (S["exp"] < cfg.symbol_exp_floor or S["pf"] < cfg.symbol_pf_floor):
        return False, -999.0, "SYMBOL_VETO"

    recent_exp = R["exp"] if R["n"] >= 6 else E["exp"]
    symbol_exp = S["exp"] if S["n"] >= 5 else E["exp"]
    blended = 0.25 * F["exp"] + 0.35 * E["exp"] + 0.25 * recent_exp + 0.15 * symbol_exp
    penalty = cfg.penalty_coeff * E["sd"] / math.sqrt(max(E["n"], 1.0))
    score = blended - penalty
    if score <= cfg.score_min:
        return False, score, "CONFIDENCE_VETO"
    return True, score, "PASS"


def run_router(shadow: list[dict[str, Any]], cfg: RouterConfig) -> tuple[list[dict[str, Any]], dict[str, int]]:
    ordered = sorted(shadow, key=lambda x: (x["signal_at"], x["symbol"], x["setup"]))
    by_exit = sorted(shadow, key=lambda x: x["exit_at"])
    history: list[dict[str, Any]] = []
    active_until: dict[str, datetime] = {}
    selected: list[dict[str, Any]] = []
    reasons: dict[str, int] = defaultdict(int)
    p = 0
    k = 0
    while k < len(ordered):
        signal_at = ordered[k]["signal_at"]
        now = datetime.fromisoformat(signal_at)
        while p < len(by_exit) and datetime.fromisoformat(by_exit[p]["exit_at"]) < now:
            history.append(by_exit[p])
            p += 1
        group: list[dict[str, Any]] = []
        while k < len(ordered) and ordered[k]["signal_at"] == signal_at:
            group.append(ordered[k])
            k += 1
        ranked: list[tuple[float, dict[str, Any]]] = []
        for c in group:
            if active_until.get(c["symbol"], datetime.min.replace(tzinfo=timezone.utc)) >= now:
                reasons["ACTIVE_SYMBOL"] += 1
                continue
            ok, score, reason = score_candidate(c, history, now, cfg)
            if not ok:
                reasons[reason] += 1
                continue
            ranked.append((score, c))
        ranked.sort(key=lambda x: x[0], reverse=True)
        for score, c in ranked[:2]:
            t = dict(c)
            t["adaptive_score"] = round(score, 6)
            t["router_config"] = cfg.config_id
            selected.append(t)
            active_until[c["symbol"]] = datetime.fromisoformat(c["exit_at"])
            reasons["SELECTED"] += 1
    return selected, dict(reasons)


def in_period(trades: list[dict[str, Any]], start: str | None, end: str) -> list[dict[str, Any]]:
    end_dt = datetime.fromisoformat(end + "T23:59:59+00:00")
    start_dt = None if start is None else datetime.fromisoformat(start + "T00:00:00+00:00")
    return [
        t for t in trades
        if (start_dt is None or datetime.fromisoformat(t["entry_at"]) >= start_dt)
        and datetime.fromisoformat(t["entry_at"]) <= end_dt
    ]


def bootstrap_positive_fraction(trades: list[dict[str, Any]], samples: int = 1000) -> float:
    if not trades:
        return 0.0
    rs = [float(t["net_r"]) for t in trades]
    rng = random.Random(SEED + len(rs))
    positive = 0
    for _ in range(samples):
        total = sum(rng.choice(rs) for _ in rs)
        positive += int(total > 0)
    return positive / samples


def quality(trades: list[dict[str, Any]]) -> dict[str, Any]:
    m = metrics(trades)
    if not trades:
        return {"metrics": m, "bootstrap_positive_fraction": 0.0, "basic_positive": False}
    b = bootstrap_positive_fraction(trades)
    n = int(m.get("trades", 0) or 0)
    exp = float(m.get("expectancy_r", 0.0) or 0.0)
    pf = float(m.get("profit_factor", 0.0) or 0.0)
    dd = float(m.get("max_drawdown_pct_at_0_5pct_risk", 0.0) or 0.0)
    positive = n >= 12 and exp >= 0.03 and pf >= 1.08 and b >= 0.65 and dd <= 10.0
    return {"metrics": m, "bootstrap_positive_fraction": round(b, 4), "basic_positive": positive}


def is_neighbor(a: RouterConfig, b: RouterConfig) -> bool:
    distance = (
        abs(a.sample_level - b.sample_level)
        + abs(a.edge_level - b.edge_level)
        + abs(a.confidence_level - b.confidence_level)
    )
    return distance <= 1


def choose_config(
    configs: list[RouterConfig],
    routed: dict[str, list[dict[str, Any]]],
    train_end: str,
) -> tuple[RouterConfig | None, dict[str, Any]]:
    train_q: dict[str, dict[str, Any]] = {}
    for cfg in configs:
        train_q[cfg.config_id] = quality(in_period(routed[cfg.config_id], None, train_end))

    candidates: list[tuple[float, RouterConfig, dict[str, Any]]] = []
    for cfg in configs:
        own = train_q[cfg.config_id]
        if not own["basic_positive"]:
            continue
        neighbors = [x for x in configs if is_neighbor(cfg, x)]
        nq = [train_q[x.config_id] for x in neighbors]
        positive_fraction = sum(bool(x["basic_positive"]) for x in nq) / max(1, len(nq))
        exps = [float(x["metrics"].get("expectancy_r", 0.0) or 0.0) for x in nq]
        pfs = [float(x["metrics"].get("profit_factor", 0.0) or 0.0) for x in nq]
        median_exp = statistics.median(exps) if exps else 0.0
        median_pf = statistics.median(pfs) if pfs else 0.0
        if positive_fraction < 0.50 or median_exp <= 0.0 or median_pf <= 1.0:
            continue
        m = own["metrics"]
        n = float(m.get("trades", 0) or 0)
        exp = float(m.get("expectancy_r", 0.0) or 0.0)
        pf = max(1e-9, float(m.get("profit_factor", 0.0) or 0.0))
        dd = float(m.get("max_drawdown_pct_at_0_5pct_risk", 0.0) or 0.0)
        boot = float(own["bootstrap_positive_fraction"])
        shrink = math.sqrt(n / (n + 20.0))
        robust_score = (
            0.40 * median_exp
            + 0.30 * exp * shrink
            + 0.08 * math.log(min(pf, 5.0))
            + 0.12 * boot
            + 0.10 * positive_fraction
            - 0.015 * dd
        )
        detail = {
            "neighbor_count": len(neighbors),
            "positive_neighbor_fraction": round(positive_fraction, 4),
            "neighbor_median_expectancy_r": round(median_exp, 6),
            "neighbor_median_profit_factor": round(median_pf, 4),
            "robust_score": round(robust_score, 6),
            "train_quality": own,
        }
        candidates.append((robust_score, cfg, detail))

    if not candidates:
        return None, {
            "decision": "NO_TRADE_CONFIG",
            "reason": "No parameter neighborhood met anchored training robustness gates.",
            "positive_configs": sum(bool(x["basic_positive"]) for x in train_q.values()),
            "config_count": len(configs),
        }
    candidates.sort(key=lambda x: (x[0], x[1].config_id), reverse=True)
    _, best, detail = candidates[0]
    detail = dict(detail)
    detail["decision"] = "SELECT_CONFIG"
    detail["selected_config"] = asdict(best)
    detail["positive_configs"] = sum(bool(x["basic_positive"]) for x in train_q.values())
    detail["config_count"] = len(configs)
    return best, detail


def reprice(trades: list[dict[str, Any]], cost_r: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in trades:
        x = dict(t)
        x["cost_r"] = cost_r
        x["net_r"] = round(float(t["gross_r"]) - cost_r, 6)
        out.append(x)
    return out


def summarize_panel(trades: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "base_cost_0_05R": metrics(reprice(trades, 0.05)),
        "stress_cost_0_10R": metrics(reprice(trades, 0.10)),
        "severe_cost_0_15R": metrics(reprice(trades, 0.15)),
        "by_setup": {},
        "by_symbol": {},
    }
    for setup in sorted({t["setup"] for t in trades}):
        out["by_setup"][setup] = metrics(reprice([t for t in trades if t["setup"] == setup], 0.10))
    for symbol in sorted({t["symbol"] for t in trades}):
        out["by_symbol"][symbol] = metrics(reprice([t for t in trades if t["symbol"] == symbol], 0.10))
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
            coverage[symbol] = {
                "rows": len(rows),
                "source": source,
                "first": rows[0]["dt"].isoformat(),
                "last": rows[-1]["dt"].isoformat(),
                "shadow": len(xs),
            }
            print("DATA", symbol, source, len(rows), "shadow", len(xs))
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")

    configs = config_grid()
    routed: dict[str, list[dict[str, Any]]] = {}
    route_reasons: dict[str, dict[str, int]] = {}
    for cfg in configs:
        trades, reasons = run_router(shadow, cfg)
        routed[cfg.config_id] = trades
        route_reasons[cfg.config_id] = reasons

    folds = [
        ("F1", "2016-12-31", "2017-02-01", "2018-12-31"),
        ("F2", "2018-12-31", "2019-02-01", "2020-12-31"),
        ("F3", "2020-12-31", "2021-02-01", "2022-12-31"),
        ("F4", "2022-12-31", "2023-02-01", "2024-12-31"),
        ("F5", "2024-12-31", "2025-02-01", "2026-09-30"),
    ]
    fold_rows: list[dict[str, Any]] = []
    oos: list[dict[str, Any]] = []
    for fold_id, train_end, test_start, test_end in folds:
        chosen, selection = choose_config(configs, routed, train_end)
        if chosen is None:
            test_trades: list[dict[str, Any]] = []
            chosen_id = "NO_TRADE"
        else:
            test_trades = in_period(routed[chosen.config_id], test_start, test_end)
            chosen_id = chosen.config_id
            for t in test_trades:
                x = dict(t)
                x["oos_fold"] = fold_id
                x["trained_through"] = train_end
                oos.append(x)
        fold_row = {
            "fold": fold_id,
            "train_end": train_end,
            "purge_days": PURGE_DAYS,
            "test_start": test_start,
            "test_end": test_end,
            "chosen_config": chosen_id,
            "selection": selection,
            "test_base": metrics(reprice(test_trades, 0.05)),
            "test_stress": metrics(reprice(test_trades, 0.10)),
            "test_severe": metrics(reprice(test_trades, 0.15)),
        }
        fold_rows.append(fold_row)
        sm = fold_row["test_stress"]
        print(
            "FOLD", fold_id, "train_end=", train_end, "cfg=", chosen_id,
            "n=", sm.get("trades"), "net_r=", sm.get("net_r"),
            "exp=", sm.get("expectancy_r"), "pf=", sm.get("profit_factor"),
        )

    base_cfg = next(c for c in configs if c.config_id == "S1E1C1")
    base_oos: list[dict[str, Any]] = []
    for fold_id, _, test_start, test_end in folds:
        for t in in_period(routed[base_cfg.config_id], test_start, test_end):
            x = dict(t)
            x["oos_fold"] = fold_id
            base_oos.append(x)

    result = {
        "research_only": True,
        "execution_influence": False,
        "live_execution_enabled": False,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "selector_future_information": False,
            "anchored_expanding_training": True,
            "purge_days_between_train_test": PURGE_DAYS,
            "parameter_grid_size": len(configs),
            "grid_design": "3x3x3 neighborhood around V3 sample/edge/confidence thresholds",
            "neighborhood_gate": "own positive plus >=50% direct-neighbor positive; positive neighborhood medians",
            "online_test_adaptation": "Within each OOS fold, fixed thresholds may learn only from shadow trades whose exits occurred before the current signal.",
            "costs_r": [0.05, 0.10, 0.15],
            "important_note": "The grid is research-informed by V1-V3; fold selection is purged and past-only, but the total 2012-2026 archive is not a pristine never-seen dataset.",
        },
        "coverage": coverage,
        "errors": errors,
        "shadow_candidates": len(shadow),
        "folds": fold_rows,
        "oos_results": summarize_panel(oos),
        "oos_trade_count": len(oos),
        "oos_trades": oos,
        "v3_base_config_reference": {
            "config": asdict(base_cfg),
            "oos_results": summarize_panel(base_oos),
            "oos_trade_count": len(base_oos),
        },
        "config_route_counts": {k: len(v) for k, v in routed.items()},
        "config_selection_reasons": route_reasons,
    }
    print("RESULT_JSON=" + json.dumps(result, separators=(",", ":"), default=str))
    for label, m in (
        ("BASE", result["oos_results"]["base_cost_0_05R"]),
        ("STRESS", result["oos_results"]["stress_cost_0_10R"]),
        ("SEVERE", result["oos_results"]["severe_cost_0_15R"]),
    ):
        print(
            "OOS", label, "n=", m.get("trades"), "wr=", m.get("win_rate"),
            "net_r=", m.get("net_r"), "exp=", m.get("expectancy_r"),
            "pf=", m.get("profit_factor"), "ret=", m.get("total_return_pct_at_0_5pct_risk"),
            "dd=", m.get("max_drawdown_pct_at_0_5pct_risk"),
        )
    ref = result["v3_base_config_reference"]["oos_results"]["stress_cost_0_10R"]
    print("V3_REFERENCE_STRESS", "n=", ref.get("trades"), "net_r=", ref.get("net_r"), "exp=", ref.get("expectancy_r"), "pf=", ref.get("profit_factor"))


if __name__ == "__main__":
    main()
