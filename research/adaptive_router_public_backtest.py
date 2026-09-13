from __future__ import annotations

import csv
import io
import json
import math
import random
import statistics
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Iterable

# Research-only frozen proxy for the Adaptive Regime Router discussed in chat.
# No parameter optimization is performed. Signals use only information available
# at the signal-bar close; execution is at the next bar open.

START = datetime(2012, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 9, 14, tzinfo=timezone.utc)

SYMBOLS = [
    "AUDUSD", "EURCHF", "EURGBP", "EURJPY", "EURUSD", "GBPJPY",
    "GBPUSD", "USDCAD", "USDCHF", "USDJPY", "XAUUSD",
]

YAHOO = {
    "AUDUSD": "AUDUSD=X", "EURCHF": "EURCHF=X", "EURGBP": "EURGBP=X",
    "EURJPY": "EURJPY=X", "EURUSD": "EURUSD=X", "GBPJPY": "GBPJPY=X",
    "GBPUSD": "GBPUSD=X", "USDCAD": "USDCAD=X", "USDCHF": "USDCHF=X",
    "USDJPY": "USDJPY=X", "XAUUSD": "GC=F",
}


def get_text(url: str, timeout: int = 45, retries: int = 3) -> str:
    headers = {"User-Agent": "Mozilla/5.0 adaptive-router-research/1.0"}
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as exc:  # pragma: no cover - network path
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"download failed after {retries} attempts: {url}: {last}")


def parse_dt(text: str) -> datetime:
    text = text.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y.%m.%d %H:%M", "%Y.%m.%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    raise ValueError(text)


def normalize_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            dt = r["dt"] if isinstance(r["dt"], datetime) else parse_dt(str(r["dt"]))
            o, h, l, c = (float(r[k]) for k in ("open", "high", "low", "close"))
        except (KeyError, ValueError, TypeError):
            continue
        if not (math.isfinite(o) and math.isfinite(h) and math.isfinite(l) and math.isfinite(c)):
            continue
        if min(o, h, l, c) <= 0 or h < max(o, c) or l > min(o, c) or h < l:
            continue
        if START <= dt <= END:
            out.append({"dt": dt, "open": o, "high": h, "low": l, "close": c})
    out.sort(key=lambda x: x["dt"])
    # deterministic duplicate removal
    dedup: dict[datetime, dict[str, Any]] = {r["dt"]: r for r in out}
    return [dedup[k] for k in sorted(dedup)]


def fetch_stooq_daily(symbol: str) -> list[dict[str, Any]]:
    url = (
        "https://stooq.com/q/d/l/?s=" + symbol.lower() +
        "&d1=20120101&d2=20260914&i=d"
    )
    text = get_text(url)
    if "No data" in text or len(text.splitlines()) < 100:
        raise RuntimeError("stooq returned insufficient rows")
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for r in reader:
        keys = {k.lower(): v for k, v in r.items() if k}
        rows.append({
            "dt": keys.get("date"), "open": keys.get("open"), "high": keys.get("high"),
            "low": keys.get("low"), "close": keys.get("close"),
        })
    return normalize_rows(rows)


def fetch_yahoo_daily(symbol: str) -> list[dict[str, Any]]:
    ticker = YAHOO[symbol]
    p1 = int(START.timestamp())
    p2 = int(END.timestamp())
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(ticker, safe="") +
        f"?period1={p1}&period2={p2}&interval=1d&events=history&includeAdjustedClose=true"
    )
    data = json.loads(get_text(url))
    result = data["chart"]["result"][0]
    ts = result.get("timestamp", [])
    q = result["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        try:
            vals = [q[k][i] for k in ("open", "high", "low", "close")]
            if any(v is None for v in vals):
                continue
            rows.append({
                "dt": datetime.fromtimestamp(t, tz=timezone.utc),
                "open": vals[0], "high": vals[1], "low": vals[2], "close": vals[3],
            })
        except (IndexError, TypeError):
            continue
    return normalize_rows(rows)


def fetch_daily(symbol: str) -> tuple[list[dict[str, Any]], str]:
    errors = []
    for name, fn in (("STOOQ", fetch_stooq_daily), ("YAHOO", fetch_yahoo_daily)):
        try:
            rows = fn(symbol)
            if len(rows) >= 500:
                return rows, name
            errors.append(f"{name}: only {len(rows)} rows")
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    raise RuntimeError("; ".join(errors))


def fetch_h4(symbol: str) -> list[dict[str, Any]]:
    url = (
        "https://raw.githubusercontent.com/komo135/forex-historical-data/main/"
        f"{symbol}/{symbol}h4.csv"
    )
    text = get_text(url)
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for r in reader:
        keys = {k.lower(): v for k, v in r.items() if k}
        rows.append({
            "dt": keys.get("date") or keys.get("time"),
            "open": keys.get("open"), "high": keys.get("high"),
            "low": keys.get("low"), "close": keys.get("close"),
        })
    out = normalize_rows(rows)
    if len(out) < 500:
        raise RuntimeError(f"insufficient H4 rows: {len(out)}")
    return out


def ema(values: list[float], period: int) -> list[float]:
    alpha = 2.0 / (period + 1.0)
    out = [values[0]]
    for x in values[1:]:
        out.append(alpha * x + (1.0 - alpha) * out[-1])
    return out


def rolling_mean(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    s = 0.0
    for i, x in enumerate(values):
        s += x
        if i >= period:
            s -= values[i - period]
        if i >= period - 1:
            out[i] = s / period
    return out


def rolling_std(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for i in range(period - 1, len(values)):
        out[i] = statistics.pstdev(values[i - period + 1:i + 1])
    return out


def indicators(rows: list[dict[str, Any]]) -> dict[str, list[Any]]:
    close = [r["close"] for r in rows]
    high = [r["high"] for r in rows]
    low = [r["low"] for r in rows]
    e20, e50, e200 = ema(close, 20), ema(close, 50), ema(close, 200)

    tr = []
    plus_dm, minus_dm = [], []
    for i in range(len(rows)):
        if i == 0:
            tr.append(high[i] - low[i])
            plus_dm.append(0.0); minus_dm.append(0.0)
        else:
            tr.append(max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1])))
            up = high[i] - high[i-1]
            dn = low[i-1] - low[i]
            plus_dm.append(up if up > dn and up > 0 else 0.0)
            minus_dm.append(dn if dn > up and dn > 0 else 0.0)
    atr = rolling_mean(tr, 14)
    tr14 = rolling_mean(tr, 14)
    pdm14 = rolling_mean(plus_dm, 14)
    mdm14 = rolling_mean(minus_dm, 14)
    dx: list[float] = [0.0] * len(rows)
    for i in range(len(rows)):
        if tr14[i] and tr14[i] > 0 and pdm14[i] is not None and mdm14[i] is not None:
            pdi = 100.0 * pdm14[i] / tr14[i]
            mdi = 100.0 * mdm14[i] / tr14[i]
            den = pdi + mdi
            dx[i] = 100.0 * abs(pdi - mdi) / den if den > 0 else 0.0
    adx = rolling_mean(dx, 14)

    gains = [0.0]
    losses = [0.0]
    for i in range(1, len(close)):
        d = close[i] - close[i-1]
        gains.append(max(d, 0.0)); losses.append(max(-d, 0.0))
    ag = rolling_mean(gains, 14); al = rolling_mean(losses, 14)
    rsi: list[float | None] = [None] * len(rows)
    for i in range(len(rows)):
        if ag[i] is not None and al[i] is not None:
            if al[i] == 0:
                rsi[i] = 100.0
            else:
                rs = ag[i] / al[i]
                rsi[i] = 100.0 - 100.0 / (1.0 + rs)
    sma20 = rolling_mean(close, 20)
    std20 = rolling_std(close, 20)
    return {
        "close": close, "e20": e20, "e50": e50, "e200": e200,
        "tr": tr, "atr": atr, "adx": adx, "rsi": rsi, "sma20": sma20, "std20": std20,
    }


def median_prior(seq: list[float | None], i: int, n: int) -> float | None:
    vals = [x for x in seq[max(0, i-n):i] if x is not None and x > 0]
    return statistics.median(vals) if vals else None


def classify_signal(rows: list[dict[str, Any]], ind: dict[str, list[Any]], i: int) -> tuple[str, str] | None:
    # Signal is generated at bar i close using only <= i data.
    if i < 220 or i + 1 >= len(rows):
        return None
    r = rows[i]
    atr = ind["atr"][i]
    adx = ind["adx"][i]
    rsi = ind["rsi"][i]
    sma20 = ind["sma20"][i]
    std20 = ind["std20"][i]
    if not atr or atr <= 0 or adx is None or rsi is None or sma20 is None or std20 is None:
        return None

    e20, e50, e200 = ind["e20"][i], ind["e50"][i], ind["e200"][i]
    prev20_hi = max(x["high"] for x in rows[i-20:i])
    prev20_lo = min(x["low"] for x in rows[i-20:i])
    rng = max(r["high"] - r["low"], 1e-12)
    body = abs(r["close"] - r["open"])
    close_loc = (r["close"] - r["low"]) / rng
    med_atr50 = median_prior(ind["atr"], i, 50) or atr

    trend_long = adx >= 22 and e20 > e50 > e200 and r["close"] > e50
    trend_short = adx >= 22 and e20 < e50 < e200 and r["close"] < e50
    range_regime = adx <= 18 and abs(e20 - e50) / atr < 0.55
    expansion = ind["tr"][i] >= 1.35 * atr or atr >= 1.18 * med_atr50

    # 1) Liquidity sweep / reclaim proxy. Avoid fighting the strongest directional state.
    if adx < 30:
        if r["low"] < prev20_lo - 0.05 * atr and r["close"] > prev20_lo and r["close"] > r["open"] and close_loc >= 0.62:
            return "LIQUIDITY_SWEEP", "LONG"
        if r["high"] > prev20_hi + 0.05 * atr and r["close"] < prev20_hi and r["close"] < r["open"] and close_loc <= 0.38:
            return "LIQUIDITY_SWEEP", "SHORT"

    # 2) High-quality trend pullback continuation.
    if trend_long and r["low"] <= e20 + 0.20 * atr and r["close"] > e20 and r["close"] > r["open"] and body >= 0.25 * atr and r["close"] > rows[i-1]["close"]:
        return "TREND_PULLBACK", "LONG"
    if trend_short and r["high"] >= e20 - 0.20 * atr and r["close"] < e20 and r["close"] < r["open"] and body >= 0.25 * atr and r["close"] < rows[i-1]["close"]:
        return "TREND_PULLBACK", "SHORT"

    # 3) Volatility expansion breakout proxy (not exact London/NY session on public broker timestamps).
    if expansion and adx >= 20 and body >= 0.50 * atr:
        if r["close"] > prev20_hi + 0.03 * atr and e20 > e50:
            return "EXPANSION_BREAKOUT", "LONG"
        if r["close"] < prev20_lo - 0.03 * atr and e20 < e50:
            return "EXPANSION_BREAKOUT", "SHORT"

    # 4) Range-only mean reversion after an outer-band rejection.
    lower = sma20 - 1.7 * std20
    upper = sma20 + 1.7 * std20
    if range_regime:
        if r["low"] < lower and r["close"] > lower and r["close"] > r["open"] and rsi <= 42:
            return "MEAN_REVERSION", "LONG"
        if r["high"] > upper and r["close"] < upper and r["close"] < r["open"] and rsi >= 58:
            return "MEAN_REVERSION", "SHORT"
    return None


SETUP_PARAMS = {
    "LIQUIDITY_SWEEP": (1.80, 0.15),
    "TREND_PULLBACK": (2.00, None),
    "EXPANSION_BREAKOUT": (2.20, None),
    "MEAN_REVERSION": (1.40, None),
}


def backtest_symbol(symbol: str, rows: list[dict[str, Any]], timeframe: str, cost_r: float) -> list[dict[str, Any]]:
    ind = indicators(rows)
    trades: list[dict[str, Any]] = []
    i = 220
    max_hold = 10 if timeframe == "D1" else 18
    while i < len(rows) - 2:
        sig = classify_signal(rows, ind, i)
        if not sig:
            i += 1
            continue
        setup, side = sig
        entry_i = i + 1
        entry = rows[entry_i]["open"]
        atr = ind["atr"][i]
        if not atr or atr <= 0:
            i += 1
            continue
        rr, sweep_pad = SETUP_PARAMS[setup]
        if setup == "LIQUIDITY_SWEEP":
            if side == "LONG":
                stop = rows[i]["low"] - float(sweep_pad) * atr
                risk = entry - stop
            else:
                stop = rows[i]["high"] + float(sweep_pad) * atr
                risk = stop - entry
        else:
            stop_mult = {"TREND_PULLBACK": 1.20, "EXPANSION_BREAKOUT": 1.10, "MEAN_REVERSION": 1.00}[setup]
            risk = stop_mult * atr
            stop = entry - risk if side == "LONG" else entry + risk
        if risk <= 0 or risk / entry > 0.15:
            i += 1
            continue
        target = entry + rr * risk if side == "LONG" else entry - rr * risk

        gross_r = None
        exit_i = min(entry_i + max_hold, len(rows) - 1)
        exit_reason = "TIME"
        for j in range(entry_i, min(entry_i + max_hold, len(rows) - 1) + 1):
            b = rows[j]
            if side == "LONG":
                hit_sl = b["low"] <= stop
                hit_tp = b["high"] >= target
            else:
                hit_sl = b["high"] >= stop
                hit_tp = b["low"] <= target
            if hit_sl and hit_tp:
                gross_r = -1.0  # conservative intrabar ambiguity
                exit_i = j; exit_reason = "SL_AMBIGUOUS_FIRST"; break
            if hit_sl:
                gross_r = -1.0
                exit_i = j; exit_reason = "SL"; break
            if hit_tp:
                gross_r = rr
                exit_i = j; exit_reason = "TP"; break
        if gross_r is None:
            px = rows[exit_i]["close"]
            gross_r = (px - entry) / risk if side == "LONG" else (entry - px) / risk
            # prevent a time-exit outlier caused by data anomalies dominating a frozen test
            gross_r = max(-1.5, min(rr, gross_r))
        net_r = gross_r - cost_r
        trades.append({
            "symbol": symbol, "timeframe": timeframe, "setup": setup, "side": side,
            "signal_at": rows[i]["dt"].isoformat(), "entry_at": rows[entry_i]["dt"].isoformat(),
            "exit_at": rows[exit_i]["dt"].isoformat(), "gross_r": round(gross_r, 6),
            "net_r": round(net_r, 6), "cost_r": cost_r, "exit_reason": exit_reason,
        })
        i = max(i + 1, exit_i + 1)
    return trades


def metrics(trades: list[dict[str, Any]], risk_fraction: float = 0.005) -> dict[str, Any]:
    if not trades:
        return {"trades": 0}
    rs = [float(t["net_r"]) for t in trades]
    wins = [x for x in rs if x > 0]
    losses = [x for x in rs if x <= 0]
    gp = sum(wins); gl = abs(sum(losses))
    pf = gp / gl if gl > 0 else float("inf")
    equity = 1.0; peak = 1.0; max_dd = 0.0
    for t in sorted(trades, key=lambda x: x["entry_at"]):
        equity *= max(0.0001, 1.0 + risk_fraction * float(t["net_r"]))
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
    first = datetime.fromisoformat(min(t["entry_at"] for t in trades))
    last = datetime.fromisoformat(max(t["exit_at"] for t in trades))
    years = max((last - first).days / 365.25, 1 / 365.25)
    cagr = equity ** (1.0 / years) - 1.0 if equity > 0 else -1.0
    return {
        "trades": len(trades), "wins": len(wins), "win_rate": round(len(wins) / len(rs), 6),
        "net_r": round(sum(rs), 4), "expectancy_r": round(statistics.mean(rs), 6),
        "profit_factor": None if math.isinf(pf) else round(pf, 4),
        "max_drawdown_pct_at_0_5pct_risk": round(max_dd * 100, 4),
        "total_return_pct_at_0_5pct_risk": round((equity - 1.0) * 100, 4),
        "cagr_pct_at_0_5pct_risk": round(cagr * 100, 4),
        "first_trade": first.date().isoformat(), "last_trade": last.date().isoformat(),
    }


def subset_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"full": metrics(trades), "by_setup": {}, "by_symbol": {}, "periods": {}}
    for setup in sorted({t["setup"] for t in trades}):
        out["by_setup"][setup] = metrics([t for t in trades if t["setup"] == setup])
    for symbol in sorted({t["symbol"] for t in trades}):
        out["by_symbol"][symbol] = metrics([t for t in trades if t["symbol"] == symbol])
    periods = [(2012, 2018), (2019, 2022), (2023, 2026)]
    for a, b in periods:
        sel = [t for t in trades if a <= datetime.fromisoformat(t["entry_at"]).year <= b]
        out["periods"][f"{a}-{b}"] = metrics(sel)
    return out


def bootstrap_positive_fraction(trades: list[dict[str, Any]], n: int = 1000) -> dict[str, Any]:
    if not trades:
        return {"samples": 0}
    rng = random.Random(20260913)
    rs = [float(t["net_r"]) for t in trades]
    totals = []
    for _ in range(n):
        totals.append(sum(rng.choice(rs) for _ in rs))
    totals.sort()
    return {
        "samples": n,
        "positive_fraction": round(sum(x > 0 for x in totals) / n, 4),
        "p05_net_r": round(totals[int(0.05 * (n - 1))], 4),
        "median_net_r": round(statistics.median(totals), 4),
        "p95_net_r": round(totals[int(0.95 * (n - 1))], 4),
    }


def coverage(rows_by_symbol: dict[str, list[dict[str, Any]]], sources: dict[str, str]) -> dict[str, Any]:
    return {
        s: {
            "rows": len(rows), "first": rows[0]["dt"].isoformat(), "last": rows[-1]["dt"].isoformat(),
            "source": sources.get(s, "unknown"),
        }
        for s, rows in sorted(rows_by_symbol.items()) if rows
    }


def main() -> None:
    daily: dict[str, list[dict[str, Any]]] = {}
    daily_src: dict[str, str] = {}
    h4: dict[str, list[dict[str, Any]]] = {}
    h4_src: dict[str, str] = {}
    errors: dict[str, list[str]] = {"D1": [], "H4": []}

    for symbol in SYMBOLS:
        try:
            rows, source = fetch_daily(symbol)
            daily[symbol] = rows; daily_src[symbol] = source
            print(f"DATA D1 {symbol} {source} n={len(rows)} {rows[0]['dt'].date()}->{rows[-1]['dt'].date()}")
        except Exception as exc:
            errors["D1"].append(f"{symbol}: {exc}")
            print(f"DATA D1 FAIL {symbol}: {exc}")
        try:
            rows = fetch_h4(symbol)
            h4[symbol] = rows; h4_src[symbol] = "KOMO135_GITHUB_APACHE2"
            print(f"DATA H4 {symbol} n={len(rows)} {rows[0]['dt'].date()}->{rows[-1]['dt'].date()}")
        except Exception as exc:
            errors["H4"].append(f"{symbol}: {exc}")
            print(f"DATA H4 FAIL {symbol}: {exc}")

    # Base cost assumptions are expressed as fraction of initial risk (R), not pips.
    # This makes the cross-instrument comparison conservative and scale-free.
    panels: dict[str, Any] = {}
    all_trades_by_panel: dict[str, list[dict[str, Any]]] = {}
    for panel_name, universe, tf, cost in (
        ("D1_BASE", daily, "D1", 0.05),
        ("D1_STRESS_COST", daily, "D1", 0.10),
        ("H4_BASE", h4, "H4", 0.08),
        ("H4_STRESS_COST", h4, "H4", 0.15),
    ):
        trades: list[dict[str, Any]] = []
        for symbol, rows in universe.items():
            trades.extend(backtest_symbol(symbol, rows, tf, cost))
        trades.sort(key=lambda x: x["entry_at"])
        all_trades_by_panel[panel_name] = trades
        panels[panel_name] = subset_metrics(trades)
        panels[panel_name]["bootstrap"] = bootstrap_positive_fraction(trades)

    result = {
        "research_only": True,
        "execution_influence": False,
        "frozen_rule_version": "ADAPTIVE_ROUTER_PUBLIC_PROXY_V1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_window": [START.date().isoformat(), END.date().isoformat()],
        "method_notes": [
            "No parameter optimization or in-sample search was performed.",
            "Signals are evaluated at bar close and entered at the next bar open.",
            "If stop and target are both touched in one bar, stop is assumed first.",
            "D1 covers the long 2012-2026 robustness window when public source coverage permits.",
            "H4 is a closer SMC/structure proxy but the public komo135 dataset is expected to end around 2022.",
            "H4 public timestamps are not assumed to be UTC; expansion breakout is therefore not labeled London/NY session-specific.",
            "Returns are R-multiples. Equity return examples assume 0.5% account risk per trade and are not a broker-margin simulation.",
            "XAUUSD Yahoo fallback uses GC=F if Stooq spot data is unavailable and is clearly identified by source coverage.",
        ],
        "coverage": {"D1": coverage(daily, daily_src), "H4": coverage(h4, h4_src)},
        "errors": errors,
        "panels": panels,
        "trade_samples": {
            k: v[:20] for k, v in all_trades_by_panel.items()
        },
    }
    print("RESULT_JSON=" + json.dumps(result, separators=(",", ":"), allow_nan=False))

    for name, panel in panels.items():
        m = panel["full"]
        print(
            "SUMMARY", name,
            "trades=", m.get("trades"),
            "wr=", m.get("win_rate"),
            "net_r=", m.get("net_r"),
            "exp_r=", m.get("expectancy_r"),
            "pf=", m.get("profit_factor"),
            "dd_pct=", m.get("max_drawdown_pct_at_0_5pct_risk"),
            "return_pct=", m.get("total_return_pct_at_0_5pct_risk"),
            "cagr_pct=", m.get("cagr_pct_at_0_5pct_risk"),
        )
        for setup, sm in panel["by_setup"].items():
            print("SETUP", name, setup, "n=", sm.get("trades"), "wr=", sm.get("win_rate"), "net_r=", sm.get("net_r"), "exp=", sm.get("expectancy_r"), "pf=", sm.get("profit_factor"))
        for period, pm in panel["periods"].items():
            print("PERIOD", name, period, "n=", pm.get("trades"), "net_r=", pm.get("net_r"), "exp=", pm.get("expectancy_r"), "pf=", pm.get("profit_factor"))


if __name__ == "__main__":
    main()
