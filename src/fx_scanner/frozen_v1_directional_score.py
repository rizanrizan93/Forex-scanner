"""Read-only directional *evidence* scores for the frozen Bootstrap125 V1.

Pinned to repairs/bootstrap125_v1_20261114/STRATEGY_V1_FROZEN.md at
90172c2fba345e4221ca822c8e7d1d760a98c6b1 and the independent
necessary-predicate audit in cbot_v1_evidence.py.

These scores represent a transparent SUBSET of observable candle predicates.
They are not calibrated probabilities, equivalent native cBot entries, or
evidence of a missed order. Unknown observations never score as PASS.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any, Mapping

from .cbot_v1_evidence import current, stamp

MARKET_CONTRACT = "RIZAN_BOOTSTRAP125_MARKET_READONLY_V1"
TIMEFRAMES = {"M1": 60, "M5": 300, "H1": 3600, "H4": 14400}
SYMBOLS = ("XAUUSD", "EURUSD", "BTCUSD")


def _obj(x: Any) -> dict:
    return dict(x) if isinstance(x, Mapping) else {}


def _rows(market: Mapping | None, symbol: str, frame: str, now: datetime, minimum: int):
    """Validated, broker-closed candles; no backfill, cached-now or forming bars."""
    if not current(market, MARKET_CONTRACT, now):
        return None
    source = _obj(_obj(_obj(market).get("bars")).get(symbol)).get(frame)
    if not isinstance(source, list) or len(source) < minimum or len(source) > 10000:
        return None
    observed = stamp(market.get("observed_at"))
    sec = TIMEFRAMES[frame]
    bars = []
    last = None
    for raw in source:
        raw = _obj(raw)
        at = stamp(raw.get("timestamp"))
        values = [raw.get(k) for k in ("open", "high", "low", "close", "volume")]
        if (at is None or any(type(v) not in (float, int) or not isfinite(v) for v in values)
                or (last is not None and at <= last)):
            return None
        o, h, l, c, volume = values
        if not (0 < l <= min(o, c) <= max(o, c) <= h and volume >= 0):
            return None
        if at.second or at.microsecond or (sec <= 3600 and int(at.timestamp()) % sec != 0):
            return None
        if at + timedelta(seconds=sec) > observed:
            return None
        bars.append({"at": at, "o": o, "h": h, "l": l, "c": c})
        last = at
    age = (now - (bars[-1]["at"] + timedelta(seconds=sec))).total_seconds()
    if not 0 <= age <= max(180, sec):
        return None
    return bars


def _atr14(bars):
    if len(bars) < 15:
        return None
    trs = []
    for previous, current_bar in zip(bars, bars[1:]):
        trs.append(max(
            current_bar["h"] - current_bar["l"],
            abs(current_bar["h"] - previous["c"]),
            abs(current_bar["l"] - previous["c"]),
        ))
    if len(trs) < 14:
        return None
    value = sum(trs[:14]) / 14
    for tr in trs[14:]:
        value = (13 * value + tr) / 14
    return value if value > 0 else None


def _ema(values, period):
    if len(values) < period:
        return None
    out = sum(values[:period]) / period
    alpha = 2 / (period + 1)
    for price in values[period:]:
        out += alpha * (price - out)
    return out


def _family(name, checks):
    """checks: (label, true/false/unknown, weight, short grounded explanation)."""
    total = sum(row[2] for row in checks)
    if total != 100:
        raise ValueError("directional family weights must total 100")
    earned = sum(weight for _, ok, weight, _ in checks if ok is True)
    coverage = sum(weight for _, ok, weight, _ in checks if ok is not None)
    return {
        "family": name, "score": earned if coverage >= 75 else None,
        "earned": earned, "coverage": coverage,
        "checks": [
            {"name": label, "state": "PASS" if value is True else "FAIL" if value is False else "UNKNOWN",
             "weight": weight, "detail": explanation}
            for label, value, weight, explanation in checks
        ],
    }


def _xau(market, now):
    out = {"BUY": [], "SELL": []}
    h1 = _rows(market, "XAUUSD", "H1", now, 11)
    m5 = _rows(market, "XAUUSD", "M5", now, 7)
    for side in ("BUY", "SELL"):
        buy = side == "BUY"
        if h1 is not None:
            bar, prev = h1[-1], h1[-2]
            width = bar["h"] - bar["l"]
            body = bar["c"] - bar["o"]
            avg = sum(abs(x["c"] - x["o"]) for x in h1[-11:-1]) / 10
            color = body > 0 if buy else body < 0
            breakout = bar["c"] > prev["h"] if buy else bar["c"] < prev["l"]
            position = ((bar["c"] - bar["l"]) / width >= .55 if buy else
                        (bar["h"] - bar["c"]) / width >= .55) if width > 0 else False
            body_ok = abs(body) >= 1.5 * avg and avg > 0
            note = "H1 tertutup terakhir " + bar["at"].isoformat()
        else:
            color = breakout = position = body_ok = None
            note = "H1 broker tertutup belum tersedia/valid"
        out[side].append(_family("XAU displacement H1", [
            ("Arah body H1", color, 15, note),
            ("Close breakout H1 sebelumnya", breakout, 35, "BUY > high sebelumnya; SELL < low sebelumnya"),
            ("Body >= 1,5 × 10 body H1", body_ok, 30, "Persyaratan displacement awal"),
            ("Posisi close >= 55% range H1", position, 20, "Close relatif terhadap high/low candle"),
        ]))
        if m5 is not None:
            b = m5[-1]
            hi = max(x["h"] for x in m5[-7:-1])
            lo = min(x["l"] for x in m5[-7:-1])
            width = b["h"] - b["l"]
            ratio = (b["c"] - b["o"]) / width if width > 0 else 0.0
            color = b["c"] > b["o"] if buy else b["c"] < b["o"]
            breakout = b["c"] > hi if buy else b["c"] < lo
            intensity = ratio > .5 if buy else ratio <= -.7
            note = "M5 tertutup terakhir " + b["at"].isoformat()
        else:
            color = breakout = intensity = None
            note = "M5 broker tertutup belum tersedia/valid"
        out[side].append(_family("XAU compression M5", [
            ("Candle M5 searah", color, 15, note),
            ("Breakout 6 candle M5", breakout, 45, "BUY > high 6 M5; SELL < low 6 M5"),
            ("Body/range sesuai BUY > 0,5 / SELL <= -0,7", intensity, 40,
             "Hanya predikat pola compression; filter native lainnya belum dibuktikan"),
        ]))
    return out


def _closed_m15_from_m1(market, now):
    m1 = _rows(market, "EURUSD", "M1", now, 9 * 15)
    if m1 is None:
        return None
    groups = {}
    for bar in m1:
        at = bar["at"]
        key = at.replace(minute=at.minute // 15 * 15)
        groups.setdefault(key, []).append(bar)
    aggregates = []
    for at, group in sorted(groups.items()):
        if len(group) != 15:
            continue
        if [x["at"] for x in group] != [at + timedelta(minutes=i) for i in range(15)]:
            continue
        aggregates.append({
            "at": at, "o": group[0]["o"], "c": group[-1]["c"],
            "h": max(x["h"] for x in group), "l": min(x["l"] for x in group),
        })
    if len(aggregates) < 9:
        return None
    last = aggregates[-1]["at"] + timedelta(minutes=15)
    if not 0 <= (now - last).total_seconds() <= 1080:
        return None
    return aggregates


def _eur_seed(market, now):
    m5 = _rows(market, "EURUSD", "M5", now, 65)
    h4 = _rows(market, "EURUSD", "H4", now, 1024)
    if m5 is not None:
        last = m5[-1]
        atr = _atr14(m5)
        bullish = last["c"] > last["o"]
        breakout = last["c"] > max(x["h"] for x in m5[-65:-1]) + .05 * atr if atr else None
        note = "EUR SEED: BUY M5; 64 bar terdahulu + ATR14 RMA"
    else:
        bullish = breakout = None
        note = "M5 kurang 65 candle tertutup/terlambat"
    if h4 is not None:
        closes = [x["c"] for x in h4]
        e20, e80 = _ema(closes, 20), _ema(closes, 80)
        ema = e20 > e80
    else:
        ema = None
    return {"BUY": [_family("EUR SEED BUY saja", [
        ("M5 bullish tertutup", bullish, 20, note),
        ("Breakout 64 M5 + 0,05 ATR14", breakout, 50, "Riset candle; validasi native M1 tetap wajib"),
        ("EMA20 H4 > EMA80 H4", ema, 30, "Butuh warmup 1.024 H4 native dan bar tertutup"),
    ])], "SELL": []}


def _eur_growth(market, now):
    m15 = _closed_m15_from_m1(market, now)
    out = {"BUY": [], "SELL": []}
    for side in ("BUY", "SELL"):
        if m15 is not None:
            b = m15[-1]
            prior = m15[-9:-1]
            hi = max(x["h"] for x in prior)
            lo = min(x["l"] for x in prior)
            width = b["h"] - b["l"]
            body = (b["c"] - b["o"]) / width if width > 0 else 0
            swept = b["l"] < lo if side == "BUY" else b["h"] > hi
            reclaim = b["c"] > lo if side == "BUY" else b["c"] < hi
            strength = body > .2 if side == "BUY" else body < -.2
            note = "EUR incumbent: 8 M15 terdahulu; M15 dibentuk dari 15 M1 lengkap"
        else:
            swept = reclaim = strength = None
            note = "Butuh >=9 M15 lengkap dari M1 broker yang segar"
        out[side].append(_family("EUR incumbent M15 (parsial V1)", [
            ("Sweep ekstrem 8 candle M15", swept, 35, note),
            ("Close reclaim kembali ke range", reclaim, 35, "BUY close > low lama; SELL close < high lama"),
            ("Rasio body BUY > 0,2 / SELL < -0,2", strength, 30,
             "Bias H1/ATR native dan keluarga AsiaBuy belum diverifikasi"),
        ]))
    return out


def evaluate_bias(market: Mapping | None, *, phase: str, now: datetime):
    """Return independent BUY / SELL scores for each V1 symbol, not a portfolio signal."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone aware")
    now = now.astimezone(timezone.utc)
    valid = current(market, MARKET_CONTRACT, now)
    result = {}
    for symbol in SYMBOLS:
        active = (phase == "GROWTH" or phase == "SEED" and symbol == "EURUSD")
        families = {"BUY": [], "SELL": []}
        reason = ""
        if phase not in ("SEED", "GROWTH"):
            reason = "Fase V1 belum terverifikasi; skor ditahan"
        elif not active:
            reason = "Fase SEED hanya mengizinkan EURUSD BUY"
        elif not valid:
            reason = "Feed market LIVE 7903 tidak valid atau lebih dari 180 detik"
        elif symbol == "XAUUSD":
            families = _xau(market, now)
        elif symbol == "EURUSD":
            families = _eur_seed(market, now) if phase == "SEED" else _eur_growth(market, now)
        else:
            # No verified native BITSTAMP_BTCUSD_M1 7D series in this public feed.
            reason = "BTC membutuhkan feed asli BITSTAMP 7D dan state native; CFD broker bukan pengganti"
        scores = {}
        for side in ("BUY", "SELL"):
            eligible = [family for family in families[side] if family["score"] is not None]
            best = max(eligible, key=lambda x: x["score"]) if eligible else None
            scores[side] = {
                "score": best["score"] if best else None,
                "coverage": best["coverage"] if best else max(
                    (family["coverage"] for family in families[side]), default=0
                ),
                "family": best["family"] if best else None,
                "families": families[side],
            }
        buy, sell = scores["BUY"]["score"], scores["SELL"]["score"]
        if not active:
            dominant = "FASE TIDAK AKTIF" if phase in ("SEED", "GROWTH") else "WAIT DATA"
        elif not valid or symbol == "BTCUSD":
            dominant = "WAIT DATA"
        elif phase == "SEED" and symbol == "EURUSD":
            dominant = "BUY SAJA DIIZINKAN · belum tentu ada sinyal"
        elif buy is None or sell is None:
            dominant = "WAIT DATA"
        elif max(buy, sell) >= 65 and abs(buy - sell) >= 15:
            dominant = "BUY LEBIH KUAT" if buy > sell else "SELL LEBIH KUAT"
        else:
            dominant = "NETRAL / SETUP BELUM JELAS"
        result[symbol] = {
            "BUY": scores["BUY"], "SELL": scores["SELL"],
            "bias": dominant, "reason": reason,
            "active": active, "market_valid": valid, "phase": phase,
            "native_order_signal": "NOT_EVALUATED",
            "missed_order_verdict": "NOT_EVALUATED",
            "execution_authority": False,
        }
    return {
        "contract": "RIZAN_BOOTSTRAP125_FROZEN_DIRECTIONAL_AUDIT_READONLY_V1",
        "as_of_utc": now.isoformat(), "phase": phase, "symbols": result,
        "score_is_win_probability": False, "score_is_native_signal": False,
        "order_enabled": False, "execution_authority": False,
    }
