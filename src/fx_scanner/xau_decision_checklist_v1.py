"""RIZAN XAU checklist V1: read-only BUY/SELL condition audit, never order authority."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Mapping

CONTRACT = "RIZAN_XAU_DECISION_CHECKLIST_V1"
EXECUTION_AUTHORITY = False
CANDLE_CONTRACT = "RIZAN_XAU_CLOSED_CANDLES_READONLY_V1"
BROKER_CONTRACT = "RIZAN_XAU_CTRADER_SYMBOL_SPEC_READONLY_V1"
REQUIRED_BARS = {"H1": 210, "M15": 70, "M5": 30}


def obj(x: Any) -> dict:
    return dict(x) if isinstance(x, Mapping) else {}


def number(x: Any) -> float | None:
    if x is None or isinstance(x, bool):
        return None
    try:
        n = float(x)
        return n if isfinite(n) else None
    except (TypeError, ValueError, OverflowError):
        return None


def stamp(x: Any) -> datetime | None:
    try:
        value = x if isinstance(x, datetime) else datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        return value.astimezone(UTC) if value.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def row(key: str, name: str, state: str, why: str) -> dict:
    if state not in ("PASS", "FAIL", "UNKNOWN"):
        raise ValueError("CHECKLIST_STATUS_INVALID")
    return {"key": key, "name": name, "state": state, "why": why}


def closed_bars(feed: Mapping | None, tf: str, now: datetime) -> tuple[list[dict], str | None]:
    """Only explicit read-only cTrader closed-candle series, never current-forming bar."""
    d = obj(feed)
    if any((
        d.get("contract") != CANDLE_CONTRACT,
        d.get("symbol") != "XAUUSD",
        d.get("account_suffix") != "7903",
        d.get("source") != "CTRADER_MARKET_DATA_READ_ONLY",
        d.get("execution_authority") is not False,
        d.get("execution_influence") is not False,
    )):
        return [], "Belum ada seri candle broker tertutup yang tervalidasi"
    data = obj(d.get("bars")).get(tf)
    if not isinstance(data, list) or not REQUIRED_BARS[tf] <= len(data) <= 3000:
        return [], "Perlu minimal " + str(REQUIRED_BARS[tf]) + " candle tertutup " + tf
    span = {"H1": timedelta(hours=1), "M15": timedelta(minutes=15),
            "M5": timedelta(minutes=5)}[tf]
    out = []
    previous = None
    for item in data:
        raw = obj(item)
        at = stamp(raw.get("closed_at"))
        v = [number(raw.get(k)) for k in ("open", "high", "low", "close")]
        if (at is None or at > now or any(x is None for x in v)
                or v[2] <= 0 or v[2] > min(v[0], v[3]) or v[1] < max(v[0], v[3])):
            return [], "Candle invalid, belum tertutup, atau harga tidak masuk akal"
        if previous is not None:
            diff = at - previous
            if diff < span or diff.total_seconds() % span.total_seconds() != 0:
                return [], "Timestamp candle tidak berurutan atau salah timeframe"
        out.append({"at": at, "o": v[0], "h": v[1], "l": v[2], "c": v[3]})
        previous = at
    max_age = {"H1": 5400, "M15": 1500, "M5": 720}[tf]
    if not 0 <= (now - out[-1]["at"]).total_seconds() <= max_age:
        return [], "Candle " + tf + " terakhir sudah kedaluwarsa"
    return out, None


def ema(data: list[float], period: int) -> float:
    value = sum(data[:period]) / period
    a = 2 / (period + 1)
    for x in data[period:]:
        value = a*x + (1-a)*value
    return value


def adx14(data: list[dict]) -> dict | None:
    """Wilder smoothed true range, +DM/-DM, DX and ADX14."""
    p = 14
    if len(data) < 2*p+2:
        return None
    tr, plus, minus = [], [], []
    for i in range(1, len(data)):
        a, b = data[i], data[i-1]
        move_up, move_down = a["h"]-b["h"], b["l"]-a["l"]
        tr.append(max(a["h"]-a["l"], abs(a["h"]-b["c"]), abs(a["l"]-b["c"])))
        plus.append(move_up if move_up > 0 and move_up > move_down else 0.)
        minus.append(move_down if move_down > 0 and move_down > move_up else 0.)
    total, up, down = sum(tr[:p]), sum(plus[:p]), sum(minus[:p])
    dx = []
    dp = dm = 0.
    for i in range(p-1, len(tr)):
        if i >= p:
            total = total - total/p + tr[i]
            up = up - up/p + plus[i]
            down = down - down/p + minus[i]
        if total <= 0:
            return None
        dp, dm = 100*up/total, 100*down/total
        dx.append(100*abs(dp-dm)/(dp+dm) if dp+dm else 0.)
    if len(dx) < p:
        return None
    a = sum(dx[:p])/p
    for x in dx[p:]:
        a = (a*(p-1)+x)/p
    return {"adx": a, "plus": dp, "minus": dm}


def atr14(data: list[dict]) -> float | None:
    if len(data) < 16:
        return None
    tr = []
    for i in range(1, len(data)):
        a, b = data[i], data[i-1]
        tr.append(max(a["h"]-a["l"], abs(a["h"]-b["c"]), abs(a["l"]-b["c"])))
    a = sum(tr[:14])/14
    for x in tr[14:]:
        a = (a*13+x)/14
    return a if a > 0 else None


def structure(data: list[dict], side: str) -> tuple[bool, str]:
    """Mechanical M5 breakout, or liquidity sweep followed by price confirmation."""
    last = data[-1]
    high = max(x["h"] for x in data[-13:-1])
    low = min(x["l"] for x in data[-13:-1])
    bos = (last["c"] > high and last["c"] > last["o"]) if side == "BUY" else (
        last["c"] < low and last["c"] < last["o"])
    if bos:
        return True, "BOS M5 pada candle terakhir (breakout 12 candle)"
    for j in range(len(data)-4, len(data)-1):
        candle = data[j]
        prev = data[j-12:j]
        if side == "BUY":
            swept = candle["l"] < min(x["l"] for x in prev) and candle["c"] > min(x["l"] for x in prev)
            confirm = last["c"] > candle["h"]
        else:
            swept = candle["h"] > max(x["h"] for x in prev) and candle["c"] < max(x["h"] for x in prev)
            confirm = last["c"] < candle["l"]
        if swept and confirm:
            return True, "Liquidity sweep + MSS M5 terkonfirmasi"
    return False, "Belum ada BOS/MSS M5 atau liquidity sweep yang terkonfirmasi"


def macro_check(macro: Mapping | None, side: str) -> dict:
    q = obj(obj(macro).get("attribution_quality"))
    state, bias = str(q.get("quality_state") or "UNAVAILABLE"), str(q.get("quality_screened_bias") or "UNAVAILABLE")
    if state != "ALIGNED_CONTEXT_ONLY":
        return row("macro", "Makro: yield & USD", "UNKNOWN",
                   "V400=" + state + ", belum ada arah makro terkonfirmasi")
    want = "BULLISH_XAU" if side == "BUY" else "BEARISH_XAU"
    return row("macro", "Makro: yield & USD", "PASS" if bias == want else "FAIL",
               "V400 bias=" + bias + "; data daily hanya konteks, bukan M5 predictor")


def trend_check(bars: list[dict], err: str | None, side: str) -> dict:
    if err:
        return row("h1", "Tren H1: EMA50 / EMA200", "UNKNOWN", err)
    prices = [x["c"] for x in bars]
    e50, e200 = ema(prices, 50), ema(prices, 200)
    passed = prices[-1] > e50 > e200 if side == "BUY" else prices[-1] < e50 < e200
    return row("h1", "Tren H1: EMA50 / EMA200", "PASS" if passed else "FAIL",
               "Close=%.2f; EMA50=%.2f; EMA200=%.2f" % (prices[-1], e50, e200))


def adx_check(bars: list[dict], err: str | None, side: str) -> dict:
    if err:
        return row("m15", "ADX14 + DI M15", "UNKNOWN", err)
    v = adx14(bars)
    if not v:
        return row("m15", "ADX14 + DI M15", "UNKNOWN", "Belum dapat menghitung ADX")
    passed = v["adx"] >= 25 and (v["plus"] > v["minus"] if side == "BUY" else v["minus"] > v["plus"])
    return row("m15", "ADX14 + DI M15", "PASS" if passed else "FAIL",
               "ADX=%.1f; DI+=%.1f; DI-=%.1f; syarat ADX >=25" % (v["adx"], v["plus"], v["minus"]))


def m5_check(bars: list[dict], err: str | None, side: str) -> dict:
    if err:
        return row("m5", "SMC: BOS / MSS M5", "UNKNOWN", err)
    yes, why = structure(bars, side)
    a = atr14(bars)
    if a:
        why += " | ATR14 M5=%.2f" % a
    return row("m5", "SMC: BOS / MSS M5", "PASS" if yes else "FAIL", why)


def v404_check(decision: Mapping | None, side: str, fresh: bool) -> dict:
    if not fresh:
        return row("v404", "Konfirmasi zona V404", "UNKNOWN", "Heartbeat/harga broker belum segar")
    d = obj(decision)
    state, direction = str(d.get("state") or "UNAVAILABLE"), str(d.get("direction") or "WAIT")
    if state in ("INVALIDATED", "WAIT_V403_UNAVAILABLE", "UNAVAILABLE"):
        return row("v404", "Konfirmasi zona V404", "UNKNOWN", "V404 " + state)
    if state in ("BLOCKED_EVENT", "WAIT_CONFLICT"):
        return row("v404", "Konfirmasi zona V404", "FAIL", "V404 " + state)
    yes = state == "READY_CONFIRMED" and direction == ("LONG" if side == "BUY" else "SHORT")
    return row("v404", "Konfirmasi zona V404", "PASS" if yes else "FAIL",
               "V404=" + state + "; direction=" + direction + "; SHADOW")


def risk_check(decision: Mapping | None, spec: Mapping | None, side: str, equity: float) -> dict:
    d = obj(decision)
    if d.get("direction") != ("LONG" if side == "BUY" else "SHORT"):
        return row("risk", "SL / TP / lot / margin", "UNKNOWN",
                   "Belum ada setup V404 searah untuk menghitung risiko")
    band = obj(d.get("entry_band"))
    lower, upper = number(band.get("low")), number(band.get("high"))
    sl = number(d.get("structural_invalidation"))
    targets = d.get("targets")
    tp = number(targets[0]) if isinstance(targets, list) and targets else None
    if None in (lower, upper, sl, tp) or upper < lower or lower <= 0:
        return row("risk", "SL / TP / lot / margin", "UNKNOWN", "Harga entry, SL atau TP1 belum valid")
    entry = upper if side == "BUY" else lower
    stop_distance = (entry-sl) if side == "BUY" else (sl-entry)
    reward = (tp-entry) if side == "BUY" else (entry-tp)
    if stop_distance <= 0 or reward <= 0:
        return row("risk", "SL / TP / lot / margin", "FAIL", "SL/TP berada di sisi harga yang salah")
    rr = reward/stop_distance
    broker = obj(spec)
    if not all((
        broker.get("contract") == BROKER_CONTRACT,
        broker.get("source") == "CTRADER_SYMBOL_READ_ONLY",
        broker.get("symbol") == "XAUUSD",
        broker.get("account_suffix") == "7903",
        broker.get("execution_authority") is False,
        broker.get("execution_influence") is False,
    )):
        return row("risk", "SL / TP / lot / margin", "UNKNOWN",
                   "SL=%.2f; TP=%.2f; RR=%.2f. Minimum lot, biaya, margin FP cTrader belum diverifikasi"
                   % (sl, tp, rr))
    units, margin, cost = (number(broker.get(k)) for k in
                           ("minimum_units", "minimum_margin_usd", "roundtrip_cost_per_unit_usd"))
    if any(x is None or x < 0 for x in (units, margin, cost)) or units <= 0:
        return row("risk", "SL / TP / lot / margin", "UNKNOWN", "Spesifikasi volume/margin/biaya broker tidak valid")
    loss = units*(stop_distance+cost)
    passed = rr >= 2 and loss <= .05*equity and margin <= .50*equity
    return row("risk", "SL / TP / lot / margin", "PASS" if passed else "FAIL",
               "RR=%.2f; risiko min USD %.2f (maks USD %.2f); margin USD %.2f (maks USD %.2f)"
               % (rr, loss, .05*equity, margin, .50*equity))


def evaluate_checklist(*, decision: Mapping | None, macro_evaluation: Mapping | None,
                       candle_feed: Mapping | None = None, broker_spec: Mapping | None = None,
                       equity_usd: float = 100.0, now: datetime | None = None,
                       structure_fresh: bool = False) -> dict:
    now = now or datetime.now(UTC)
    if now.tzinfo is None or equity_usd <= 0:
        raise ValueError("Invalid timezone/equity")
    now = now.astimezone(UTC)
    history = {tf: closed_bars(candle_feed, tf, now) for tf in REQUIRED_BARS}
    result = {}
    for side in ("BUY", "SELL"):
        items = [
            macro_check(macro_evaluation, side),
            trend_check(*history["H1"], side),
            adx_check(*history["M15"], side),
            m5_check(*history["M5"], side),
            v404_check(decision, side, structure_fresh),
            risk_check(decision if structure_fresh else None, broker_spec, side, float(equity_usd)),
        ]
        passed = sum(x["state"] == "PASS" for x in items)
        failed = sum(x["state"] == "FAIL" for x in items)
        unknown = sum(x["state"] == "UNKNOWN" for x in items)
        result[side] = {
            "items": items, "passed": passed, "failed": failed,
            "unknown": unknown, "total": len(items),
            "state": "ALL_CONDITIONS_MET_SHADOW_ONLY" if passed == len(items) else "WAIT",
        }
    return {
        "contract": CONTRACT, "as_of_utc": now.isoformat(),
        "equity_reference_usd": equity_usd, "BUY": result["BUY"], "SELL": result["SELL"],
        "execution_authority": EXECUTION_AUTHORITY, "execution_influence": False,
        "order_enabled": False, "calibrated_probability": None,
    }
