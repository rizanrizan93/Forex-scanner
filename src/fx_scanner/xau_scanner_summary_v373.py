from __future__ import annotations

from datetime import datetime
from typing import Any

from .xau_yield_regime_view_v372 import yield_regime_summary


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dict(value: Any) -> dict[str, Any]:
    return dict(value or {})


def _bias_matches(direction: str, bias: Any) -> bool | None:
    raw = str(bias or "").upper()
    if raw not in {"BULLISH_XAU", "BEARISH_XAU", "GOLD_BULLISH", "GOLD_BEARISH"}:
        return None
    if direction == "LONG":
        return raw in {"BULLISH_XAU", "GOLD_BULLISH"}
    if direction == "SHORT":
        return raw in {"BEARISH_XAU", "GOLD_BEARISH"}
    return None


def _latest_released_event(event_risk: dict[str, Any]) -> dict[str, Any]:
    direct = _dict(event_risk.get("latest_released_event"))
    if direct:
        return direct
    rows = []
    for raw in list(event_risk.get("upcoming_events") or []):
        row = _dict(raw)
        if row.get("actual") is None:
            continue
        scheduled = str(row.get("scheduled_at") or "")
        rows.append((scheduled, row))
    rows.sort(key=lambda item: item[0], reverse=True)
    return rows[0][1] if rows else {}


def _zone_location(direction: str, price: float | None, zone: dict[str, Any]) -> str:
    if price is None or not zone:
        return "UNAVAILABLE"
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    if low is None or high is None:
        return "UNAVAILABLE"
    if low <= price <= high:
        return "IN_ZONE"
    if price < low:
        return "BELOW_ZONE"
    return "ABOVE_ZONE"


def _format_zone(zone: dict[str, Any]) -> str:
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    if low is None or high is None:
        return "—"
    tf = str(zone.get("timeframe") or "HTF")
    kind = "DEMAND" if str(zone.get("direction") or "").upper() == "LONG" else "SUPPLY"
    return f"{tf} {kind} {low:,.2f}–{high:,.2f}"


def _decision_state(
    *,
    direction: str,
    location: str,
    distance_atr: float | None,
    guide: dict[str, Any],
    micro: dict[str, Any],
    news: dict[str, Any],
    main_zone: dict[str, Any],
) -> tuple[str, str, str]:
    gate = str(news.get("effective_entry_state") or guide.get("state") or "WAIT").upper()
    risk_state = str(news.get("risk_state") or "CLEAR").upper()
    stage = str(micro.get("stage") or "FAR").upper()
    confirmed = bool(micro.get("confirmed"))
    early_confirmed = bool(micro.get("early_confirmed"))
    condition = str(main_zone.get("condition") or "").upper()
    quarantined = bool(main_zone.get("intraday_quarantined"))
    has_geometry = any(
        guide.get(key) is not None
        for key in (
            "entry_low",
            "entry_high",
            "confirmation_entry_reference",
            "invalidation",
        )
    )

    if risk_state in {"PRE_EVENT", "EVENT_WINDOW"}:
        return (
            "WAIT_NEWS",
            "WAIT NEWS",
            "Jangan entry baru sampai event lewat dan struktur XAU divalidasi ulang.",
        )
    if condition in {"BROKEN", "INVALID", "RETIRED"} or quarantined:
        return (
            "REBUILD",
            "ZONE INVALID / REROUTE",
            "Zona utama tidak lagi dipakai. Tunggu engine mempromosikan MAIN zone berikutnya.",
        )
    if "NO_CHASE" in gate:
        return (
            "NO_CHASE",
            "NO CHASE",
            "Arah bisa tetap valid, tetapi harga sudah terlalu jauh. Tunggu retest/entry baru.",
        )
    if confirmed and has_geometry:
        label = "LONG READY" if direction == "LONG" else "SHORT READY"
        return (
            f"READY_{direction}",
            label,
            "Konfirmasi reversal sudah lengkap. Gunakan hanya geometry entry/SL/TP yang dipublikasikan scanner.",
        )
    if early_confirmed and has_geometry:
        label = "EARLY LONG • DEMO" if direction == "LONG" else "EARLY SHORT • DEMO"
        return (
            f"EARLY_{direction}_DEMO",
            label,
            "Early confirmation tersedia untuk probe DEMO saja bila SL struktural dan RR tetap valid.",
        )
    if location == "IN_ZONE" or stage not in {"FAR", "WAIT", "UNAVAILABLE"}:
        label = "WAIT CONFIRM LONG" if direction == "LONG" else "WAIT CONFIRM SHORT"
        trigger = (
            "Tunggu sweep/touch → reclaim → MSS/CHOCH → displacement M5/M15."
        )
        return (f"WAIT_CONFIRMATION_{direction}", label, trigger)
    if distance_atr is not None and distance_atr <= 0.75:
        label = "PREPARE LONG" if direction == "LONG" else "PREPARE SHORT"
        return (
            f"PREPARE_{direction}",
            label,
            "Harga mendekati MAIN zone. Bersiap, tetapi belum entry sampai konfirmasi microstructure muncul.",
        )
    label = "WAIT FOR LONG ZONE" if direction == "LONG" else "WAIT FOR SHORT ZONE"
    return (
        f"WAIT_FOR_ZONE_{direction}",
        label,
        "Belum entry. Tunggu harga mencapai area MAIN reversal atau sampai engine mereroute ke zona baru.",
    )


def build_scanner_summary(
    *,
    sd_eval: dict[str, Any] | None,
    friend_eval: dict[str, Any] | None,
    event_risk: dict[str, Any] | None,
    macro_eval: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a single read-only decision summary from the active XAU engines.

    The summary does not create execution authority. V342 remains the structural
    authority, V357/V372 provide macro context, V192 provides event context, and
    V343 remains secondary reconstruction evidence only.
    """
    sd = _dict(sd_eval)
    friend = _dict(friend_eval)
    event = _dict(event_risk)
    macro = _dict(macro_eval)

    price = _f(sd.get("price_now"))
    main_zone = _dict(sd.get("main_reversal_zone") or sd.get("decision_zone"))
    guide = _dict(sd.get("entry_guide"))
    micro = _dict(sd.get("micro_confirmation"))
    news = _dict(sd.get("news_zone"))
    structure = _dict(sd.get("market_structure"))
    h4 = _dict(structure.get("H4"))
    h1 = _dict(structure.get("H1"))
    sr_map = _dict(sd.get("support_resistance_map"))
    destination = _dict(sd.get("structural_destination"))
    ladder = _dict(sd.get("destination_ladder"))

    direction = str(
        sd.get("expected_reversal_direction")
        or main_zone.get("direction")
        or "WAIT"
    ).upper()
    if direction not in {"LONG", "SHORT"}:
        direction = "WAIT"

    location = _zone_location(direction, price, main_zone)
    distance_atr = _f(main_zone.get("distance_atr"))

    if direction in {"LONG", "SHORT"} and main_zone:
        decision_state, decision_label, action_text = _decision_state(
            direction=direction,
            location=location,
            distance_atr=distance_atr,
            guide=guide,
            micro=micro,
            news=news,
            main_zone=main_zone,
        )
    else:
        decision_state = "WAIT_NO_MAIN_ZONE"
        decision_label = "WAIT"
        action_text = "MAIN reversal zone belum tersedia. Jangan membuat entry baru dari ringkasan ini."

    yield_summary = yield_regime_summary(macro) if macro else {
        "daily": {},
        "intraday": {},
        "alignment": "UNAVAILABLE",
        "decision_note": "Macro heartbeat belum tersedia.",
    }
    daily_yield = _dict(yield_summary.get("daily"))
    intraday_yield = _dict(yield_summary.get("intraday"))
    broader_bias = str(macro.get("broader_macro_bias") or "UNAVAILABLE")

    alignment_score = 0
    alignment_inputs = 0
    for bias in (
        broader_bias,
        daily_yield.get("gold_bias"),
        intraday_yield.get("gold_bias"),
    ):
        match = _bias_matches(direction, bias)
        if match is None:
            continue
        alignment_inputs += 1
        alignment_score += 1 if match else -1
    if alignment_inputs == 0:
        context_alignment = "UNAVAILABLE"
    elif alignment_score >= 2:
        context_alignment = "SUPPORTIVE"
    elif alignment_score <= -2:
        context_alignment = "CONFLICT"
    else:
        context_alignment = "MIXED"

    latest_event = _latest_released_event(event)
    next_event = _dict(event.get("focal_event"))
    latest_event_match = _bias_matches(direction, latest_event.get("gold_bias"))

    liquidity = sorted(
        (_dict(row) for row in list(sd.get("liquidity_candidates") or [])),
        key=lambda row: float(row.get("distance_atr") or 9999.0),
    )[:5]
    targets = [_dict(row) for row in list(guide.get("targets") or [])]
    primary_destination = _dict(ladder.get("primary") or destination)
    terminal_destination = _dict(ladder.get("terminal_scenario"))

    reasons: list[str] = []
    if main_zone:
        reasons.append(
            f"Arah struktural {direction}; MAIN zone {_format_zone(main_zone)}; location={location}."
        )
    reasons.append(
        f"H4={h4.get('state') or '—'}; H1={h1.get('state') or '—'}; micro stage={micro.get('stage') or 'WAIT'}."
    )
    reasons.append(
        "Macro alignment=" + context_alignment
        + f"; broader={broader_bias}; US10Y daily={daily_yield.get('gold_bias') or 'UNAVAILABLE'}; "
        + f"US10Y intraday={intraday_yield.get('gold_bias') or 'UNAVAILABLE'}."
    )
    if latest_event:
        event_note = str(latest_event.get("title") or "event terakhir")
        if latest_event_match is True:
            event_note += " mendukung arah scanner."
        elif latest_event_match is False:
            event_note += " berlawanan dengan arah scanner."
        else:
            event_note += " belum memberi bias numerik yang cukup."
        reasons.append(event_note)
    if not bool(micro.get("confirmed")):
        reasons.append("Konfirmasi microstructure belum lengkap; forecast bukan izin entry.")

    friend_direction = str(friend.get("direction") or "WAIT").upper()
    friend_entries = _dict(friend.get("entries"))
    friend_targets = _dict(friend.get("targets"))
    evidence = _dict(friend.get("historical_evidence"))
    oos = _dict(evidence.get("oos_2025_2026"))

    return {
        "contract": "XAU_RIZAN_SCANNER_SUMMARY_V373",
        "execution_authority": False,
        "execution_influence": False,
        "decision": {
            "state": decision_state,
            "label": decision_label,
            "direction": direction,
            "action": action_text,
            "entry_gate": str(news.get("effective_entry_state") or guide.get("state") or "WAIT"),
            "context_alignment": context_alignment,
        },
        "price": price,
        "structure": {
            "H4": h4.get("state"),
            "H1": h1.get("state"),
        },
        "main_zone": main_zone,
        "main_zone_label": _format_zone(main_zone),
        "zone_location": location,
        "distance_atr": distance_atr,
        "micro": micro,
        "entry": {
            "prepared_low": guide.get("prepared_entry_low"),
            "prepared_high": guide.get("prepared_entry_high"),
            "confirmation_reference": guide.get("confirmation_entry_reference"),
            "entry_low": guide.get("entry_low"),
            "entry_high": guide.get("entry_high"),
            "invalidation": guide.get("invalidation"),
            "targets": targets,
        },
        "support_resistance": {
            "support": _dict(sr_map.get("nearest_support")),
            "resistance": _dict(sr_map.get("nearest_resistance")),
            "flip_watch": _dict(sr_map.get("flip_watch")),
        },
        "liquidity": liquidity,
        "macro": {
            "broader_bias": broader_bias,
            "confidence": macro.get("confidence"),
            "yield": yield_summary,
            "alignment": context_alignment,
        },
        "event": {
            "state": event.get("state") or news.get("risk_state"),
            "latest_released": latest_event,
            "next_event": next_event,
        },
        "destination": {
            "primary": primary_destination,
            "terminal": terminal_destination,
        },
        "friend_evidence": {
            "direction": friend_direction,
            "state": friend.get("state"),
            "primary_entry": friend_entries.get("historical_primary_price"),
            "stop_loss": friend.get("stop_loss"),
            "targets": friend_targets,
            "oos_expectancy_r": oos.get("expectancy_r_all_fills"),
            "authority": "SECONDARY_EVIDENCE_ONLY",
        },
        "reasons": reasons,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }
