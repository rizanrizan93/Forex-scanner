"""Read-only, causally gated A -> B research map from the existing XAU V05 snapshot.

This module does not generate broker orders, forecast win probability, or change cBots.
LIMIT is an unvalidated hypothesis; CONFIRMED is the existing V05 reference path.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite

CONTRACT = "RIZAN_ZONE_PATH_DISPLAY_V1"
FAMILY = {0: "Supply / Demand", 1: "FVG", 2: "Breaker", 3: "Break struktur",
          4: "High / Low harian", 5: "EMA", 6: "Swing"}


def _time(value):
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return t.astimezone(timezone.utc) if t.tzinfo else None
    except (ValueError, TypeError):
        return None


def _price(value):
    try:
        value = float(value)
        return value if isfinite(value) and value > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _atr(zone, registry):
    """Match *published* node geometry to its ATR; never synthesize candle data."""
    when = _time(zone.get("formed_at"))
    if when is None:
        return None
    tf = {"H1": 60, "H4": 240}.get(zone.get("timeframe"))
    direction = 1 if zone.get("side") == "BUY" else -1
    for node in registry:
        if node.get("tf") != tf or node.get("direction") != direction:
            continue
        if abs(int(node.get("formed_ns", 0)) / 1e9 - when.timestamp()) > 0.002:
            continue
        if abs(float(node.get("low", 0)) - zone["low"]) > 0.0001:
            continue
        if abs(float(node.get("high", 0)) - zone["high"]) > 0.0001:
            continue
        return _price(node.get("atr"))
    return None


def _sources(snapshot):
    """Only zones whose lifecycle is checked by the snapshot, not raw registry nodes."""
    result = {}
    for zone in snapshot.get("supply_demand_zones") or []:
        if isinstance(zone, dict) and zone.get("id"):
            result[zone["id"]] = dict(zone, origin="SUPPLY_DEMAND")
    for zone in snapshot.get("watch_zones") or []:
        if isinstance(zone, dict) and zone.get("id"):
            result[zone["id"]] = dict(zone, origin="WATCH_V05")
    return list(result.values())


def _proof_of_untouched(zone, snapshot):
    """Unknown M1 history is NOT proof that a level is fresh."""
    if zone["origin"] != "WATCH_V05":
        return False
    audit = (snapshot.get("watch_checks") or {}).get(zone["id"]) or {}
    m1 = audit.get("m1_audit") or {}
    return (audit.get("first_touch_at") is None and
            audit.get("observed_touch_at") is None and
            audit.get("observation_status") == "MENUNGGU_SENTUHAN" and
            m1.get("unverified_minutes") == 0 and
            int(m1.get("m1_bars") or 0) > 0)


def _valid_zone(z):
    if z.get("origin") == "WATCH_V05":
        return z.get("state") == "WATCH_ZONE_ONLY"
    return z.get("status") == "VALID"


def _destination(source, pool, snapshot, entry, atr, now):
    """Return an untouched opposing zone B that lies ahead of A's limit entry."""
    sign = 1 if source["side"] == "BUY" else -1
    options = []
    for b in pool:
        if b["id"] == source["id"] or b.get("side") == source["side"]:
            continue
        if not _valid_zone(b) or not _proof_of_untouched(b, snapshot):
            continue
        born = _time(b.get("formed_at"))
        if not born or not 0 <= (now - born).total_seconds() <= 120 * 3600:
            continue
        near = _price(b.get("low") if sign == 1 else b.get("high"))
        if near is None or sign * (near - entry) <= 0:
            continue
        # TP is set just in front of B; never place it inside/behind A.
        tp = near - sign * 0.05 * atr
        if sign * (tp - entry) <= 0:
            continue
        options.append((sign * (tp - entry), b, tp))
    if not options:
        return None, None
    _, b, tp = min(options, key=lambda x: x[0])
    return {k: b.get(k) for k in ("id", "side", "timeframe", "family", "low", "high", "formed_at")}, tp


def build_zone_paths(snapshot, now=None):
    """Pure display projection. No simulated fill, expectancy, or execution approval."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must have timezone")
    result = dict(contract=CONTRACT, state="WAIT", reason="SNAPSHOT_TIDAK_VALID",
                  as_of=snapshot.get("as_of"), closed_at=snapshot.get("evaluated_close_at"),
                  price=None, bias={}, limit=[], confirmed=[], execution_authority=False,
                  execution_influence=False, calibrated_probability=None)
    issued = _time(snapshot.get("as_of"))
    closed = _time(snapshot.get("evaluated_close_at"))
    if (snapshot.get("contract") != "RIZAN_ZONE_V05_DASHBOARD_1" or
            snapshot.get("execution_authority") is not False or
            snapshot.get("execution_influence") is not False):
        return result
    if (not issued or not closed or
            not 0 <= (now - issued).total_seconds() <= 420 or
            not 0 <= (now - closed).total_seconds() <= 420):
        result["reason"] = "DATA_TERLAMBAT"
        return result
    price = _price(snapshot.get("price_reference"))
    if price is None:
        result["reason"] = "HARGA_TIDAK_TERSEDIA"
        return result

    result.update(state="WATCH", reason="PETA_DIHITUNG", price=price,
                  bias=snapshot.get("ema_bias") or {})
    pool = _sources(snapshot)
    registry = snapshot.get("node_registry") or []
    for a in pool:
        side = a.get("side")
        low, high = _price(a.get("low")), _price(a.get("high"))
        if side not in ("BUY", "SELL") or not low or not high or low >= high:
            continue
        sign = 1 if side == "BUY" else -1
        entry = high if sign == 1 else low  # proximal face, not a broker fill
        atr = _atr(a, registry)
        obs = (snapshot.get("watch_checks") or {}).get(a["id"]) or {}
        stop = _price(obs.get("sl")) if a["origin"] == "WATCH_V05" else None
        if stop is None and atr is not None:
            stop = low - 0.2 * atr if sign == 1 else high + 0.2 * atr
        risk = sign * (entry - stop) if stop is not None else None
        b, tp = _destination(a, pool, snapshot, entry, atr, now) if atr else (None, None)
        gross_rr = sign * (tp - entry) / risk if tp and risk and risk > 0 else None
        born = _time(a.get("formed_at"))
        age = (now - born).total_seconds() if born else None
        aligned = result["bias"].get("H1") == side and result["bias"].get("H4") == side
        reason = "MENUNGGU_HARGA"
        if not _valid_zone(a):
            reason = "PENDING_INVALIDATION_ATAU_DATA_ZONA"
        elif age is None or not 0 <= age <= 24 * 3600:
            reason = "ZONA_LEBIH_24_JAM"
        elif not _proof_of_untouched(a, snapshot):
            reason = "FIRST_TOUCH_BELUM_TERBUKTI_FRESH"
        elif (sign == 1 and price <= entry) or (sign == -1 and price >= entry):
            reason = "HARGA_SUDAH_MENCAPAI_AREA"
        elif not aligned:
            reason = "BIAS_H1_H4_TIDAK_SEARAH"
        elif stop is None or risk is None or risk <= 0 or atr is None:
            reason = "ATR_ATAU_STOP_TIDAK_TERSEDIA"
        elif b is None:
            reason = "ZONA_B_LAWAN_BELUM_TERVALIDASI"
        elif gross_rr is None or gross_rr < 1.5:
            reason = "RR_KOTOR_DI_BAWAH_1_5"
        else:
            reason = "WATCH_LIMIT_RISET_BUKAN_SINYAL_ORDER"
        result["limit"].append(dict(
            side=side, origin=a["origin"], family=FAMILY.get(a.get("family"), "Struktur"),
            source={k: a.get(k) for k in ("id", "timeframe", "low", "high", "formed_at")},
            target=b, price_at_evaluation=price, entry_reference=entry,
            sl_reference=stop, tp_reference=tp, gross_rr=gross_rr,
            state="WATCH" if reason == "WATCH_LIMIT_RISET_BUKAN_SINYAL_ORDER" else "WAIT",
            reason=reason, first_touch_verified=_proof_of_untouched(a, snapshot),
            entry_allowed=False, atr_reference=atr))
    result["limit"].sort(key=lambda a: (
        a["state"] != "WATCH", abs(a["entry_reference"] - price), a["source"]["id"]))

    for plan in snapshot.get("plans") or []:
        a = plan.get("source") or {}
        if a.get("side") not in ("BUY", "SELL"):
            continue
        confirmed = bool(plan.get("reclaim_m15_at") and plan.get("confirmation_m5_at"))
        eligible = (plan.get("state") == "ENTRY" and confirmed and
                    all(_price(plan.get(k)) for k in ("entry", "sl", "tp")) and
                    plan.get("target") is not None and
                    isinstance(plan.get("planned_net_rr"), (float, int)) and
                    plan["planned_net_rr"] >= 1.5)
        result["confirmed"].append(dict(
            side=a["side"], state="ENTRY_REFERENSI" if eligible else "WAIT",
            reason="M15_M5_LOLOS_V05" if eligible else plan.get("reason", "KONFIRMASI_BELUM_LENGKAP"),
            source=a, target=plan.get("target") if confirmed else None,
            first_touch_at=plan.get("first_touch_at"),
            reclaim_m15_at=plan.get("reclaim_m15_at"),
            confirmation_m5_at=plan.get("confirmation_m5_at"),
            entry_reference=plan.get("entry") if confirmed else None,
            sl_reference=plan.get("sl") if confirmed else None,
            tp_reference=plan.get("tp") if confirmed else None,
            net_rr=plan.get("planned_net_rr") if confirmed else None,
            entry_allowed=False))
    return result
