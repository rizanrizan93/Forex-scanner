"""Read-only pre-release expectations. No actuals, fitted probabilities or orders.

Consensus versus previous is a change expectation, never an actual surprise.
Freshness is checked again at read time, independently of publication age.
"""
from __future__ import annotations

from datetime import UTC, datetime, date
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

from .pre_news_source_fusion import (
    SECONDARY_CONSENSUS_SOURCES, _comparable_inflation_quote, canonical_event_key,
)

MIN_FORECAST_SOURCES = 3

CONTRACT = "RIZAN_PRE_NEWS_EXPECTATION_V1"
EVENT_WORKER = "ctrader_demo_xau_event_risk_v192"
MACRO_WORKER = "ctrader_demo_xau_macro_attribution_v357"
DIRECT = {"CPI", "PPI", "EMPLOYMENT", "NFP", "WAGES", "ECI", "JOLTS", "FOMC"}
INVERSE = {"UNEMPLOYMENT_RATE"}
SUPPORTED = DIRECT | INVERSE

# BLS: October 2025 all-items and core indexes were unavailable; the
# October 2026 twelve-month headline/core comparisons are not published.
# This is a release-specific exception, not a blanket CPI YoY exclusion.
OCT_2026_CPI_RELEASE = date(2026, 11, 10)
UNPUBLISHED_OCT_2026_COMPONENTS = frozenset({"CPI_YOY", "CORE_CPI_YOY"})


def _unpublished_oct_2026_cpi_yoy(event: dict[str, Any], at: datetime) -> bool:
    component = str(event.get("event_component") or canonical_event_key(str(event.get("title") or "")))
    return (at.date() == OCT_2026_CPI_RELEASE and
            event.get("category") == "CPI" and
            component in UNPUBLISHED_OCT_2026_COMPONENTS)



def timestamp(value: Any) -> datetime | None:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(UTC) if dt.tzinfo else None
    except (ValueError, TypeError):
        return None


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if isfinite(n) else None
    except (ValueError, TypeError):
        return None


def fresh(at: Any, now: datetime, limit: float) -> bool:
    dt = timestamp(at)
    return dt is not None and 0 <= (now - dt).total_seconds() <= limit


def _source_conflict(event: dict[str, Any]) -> bool:
    if str(event.get("source_agreement") or "").upper() == "SOURCE_CONFLICT":
        return True
    conflicts = event.get("conflicts") or []
    return bool(conflicts) if isinstance(conflicts, (list, tuple, set)) else bool(str(conflicts).strip())


def _scenarios(category: str) -> list[dict[str, str]]:
    inverse = category in INVERSE
    return [
        {"Rilis": "Di atas konsensus", "Implikasi awal XAU": "Cenderung mendukung" if inverse else "Cenderung menekan"},
        {"Rilis": "Sesuai konsensus", "Implikasi awal XAU": "Tergantung revisi, komponen dan positioning"},
        {"Rilis": "Di bawah konsensus", "Implikasi awal XAU": "Cenderung menekan" if inverse else "Cenderung mendukung"},
    ]


def evaluate_pre_news(snapshot: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """Consume full or compact V192/V193/V398 heartbeat payloads without mutation."""
    current = timestamp(now)
    if current is None:
        raise ValueError("now must be timezone-aware")
    by_worker: dict[str, dict[str, Any]] = {}
    for row in snapshot.get("heartbeats") or []:
        key = row.get("worker_name")
        at = timestamp(row.get("observed_at"))
        previous = timestamp(by_worker.get(key, {}).get("observed_at"))
        if at is not None and (previous is None or at > previous):
            by_worker[key] = row
    event_hb = by_worker.get(EVENT_WORKER, {})
    macro_hb = by_worker.get(MACRO_WORKER, {})
    event_details = event_hb.get("details") or {}
    risk = event_details.get("risk") or event_details.get("dashboard_projection") or {}
    macro_details = macro_hb.get("details") or {}
    macro = macro_details.get("evaluation") or macro_details.get("dashboard_projection") or {}
    reasons: list[str] = []
    if snapshot.get("publication_fresh") is False:
        reasons.append("PUBLICATION_STALE")
    if not fresh(event_hb.get("observed_at"), current, 600) or not event_hb.get("healthy"):
        reasons.append("CALENDAR_STALE_MISSING_OR_UNHEALTHY")
    if not fresh(macro_hb.get("observed_at"), current, 600) or not macro_hb.get("healthy"):
        reasons.append("MACRO_STALE_MISSING_OR_UNHEALTHY")
    events = [dict(e) for e in risk.get("upcoming_events") or []]
    if risk.get("focal_event"):
        events.append(dict(risk["focal_event"]))
    if risk.get("latest_released_event"):
        events.append(dict(risk["latest_released_event"]))
    upcoming = []
    seen = set()
    for event in events:
        at = timestamp(event.get("scheduled_at"))
        key = (event.get("title"), at)
        if at is None or at < current or event.get("category") not in SUPPORTED or key in seen:
            continue
        if event.get("currency", "USD") != "USD":
            continue
        seen.add(key)
        upcoming.append((at, event))
    upcoming.sort(key=lambda item: (item[0], str(item[1].get("title"))))
    result: dict[str, Any] = {
        "contract": CONTRACT, "observed_at": current.isoformat(),
        "state": "DATA INCOMPLETE", "expectation": "UNAVAILABLE",
        "xau_bias": "UNAVAILABLE", "conviction": "UNAVAILABLE",
        "forecast_risk": "UNAVAILABLE",
        "forecast_xau_bias": "UNAVAILABLE",
        "forecast_quorum_required": MIN_FORECAST_SOURCES,
        "forecast_quorum_met": False,
        "news_conclusion": "BELUM ADA KESIMPULAN NEWS XAU",
        "news_conclusion_status": "INSUFFICIENT",
        "news_conclusion_basis": "Menunggu forecast numerik dan data kalender yang valid.",
        "news_conclusion_components": 0,
        "probability": None, "calibration": "UNVALIDATED_HEURISTIC",
        "execution_authority": False, "execution_influence": False,
        "news_gate": str(risk.get("state") or "UNAVAILABLE"),
        "news_gate_action": str(risk.get("action") or "UNAVAILABLE"),
        "event": None, "minutes_to_event": None, "scenarios": [],
        "calendar_observed_at": event_hb.get("observed_at"),
        "macro_observed_at": macro_hb.get("observed_at"),
        "calendar_fusion_version": event_details.get("calendar_fusion_version"),
        "calendar_source_status": dict(event_details.get("source_status") or {}),
        "fusion_policy": dict(event_details.get("fusion_policy") or {}),
        "reasons": reasons, "components": [], "event_cluster": [],
        "unpublished_components": [],
    }
    # A completed release is not a pre-release forecast. Give its verified
    # actual-versus-consensus surprise priority over a stale COOL/HOT tilt.
    # This does not rewrite historical pre-release predictions.
    recent: list[tuple[datetime, dict[str, Any]]] = []
    for e in events:
        scheduled = timestamp(e.get("scheduled_at"))
        if (scheduled is None or e.get("currency", "USD") != "USD"
                or e.get("category") not in SUPPORTED):
            continue
        age = (current - scheduled).total_seconds()
        if 0 < age <= 4 * 3600:
            recent.append((scheduled, e))
    if recent:
        latest = max(at for at, _e in recent)
        # The feed repeats focal/latest-released rows inside upcoming_events.
        # Keep one observation per economic component, preferring official actuals.
        deduped: dict[str, dict[str, Any]] = {}
        for at, row in recent:
            if at != latest:
                continue
            component = str(
                row.get("event_component")
                or canonical_event_key(str(row.get("title") or ""))
            )
            prior = deduped.get(component)
            verified = (
                str(row.get("source_tier") or "").startswith("OFFICIAL_ACTUAL")
                and number(row.get("actual")) is not None
            )
            if prior is None or (
                verified and not (
                    str(prior.get("source_tier") or "").startswith("OFFICIAL_ACTUAL")
                    and number(prior.get("actual")) is not None
                )
            ):
                deduped[component] = row
        recent_cluster = list(deduped.values())
        # The worker explicitly reports an in-progress/released event; a past
        # focal record alone may instead be an obsolete fixture/calendar item.
        release_state = str(risk.get("state") or "")
        official_seen = any(
            str(e.get("source_tier") or "").startswith("OFFICIAL_ACTUAL")
            and number(e.get("actual")) is not None
            for e in recent_cluster
        )
        corroborated_seen = any(
            int(e.get("actual_source_count") or 0) >= 2
            and str(e.get("source_agreement") or "") == "MULTI_SOURCE_AGREE"
            and number(e.get("actual")) is not None
            for e in recent_cluster
        )
        preliminary_seen = any(
            int(e.get("actual_source_count") or 0) == 1
            and int(e.get("forecast_source_count") or 0) >= 3
            and str(e.get("source_agreement") or "") == "MULTI_SOURCE_AGREE"
            and number(e.get("actual")) is not None
            for e in recent_cluster
        )
        if (official_seen or corroborated_seen or preliminary_seen
                or release_state in {"EVENT_WINDOW", "POST_EVENT_DISCOVERY"}):
            result.update(
                state="POST_NEWS_PENDING", event=recent_cluster[0],
                event_time_wib=latest.astimezone(ZoneInfo("Asia/Jakarta")).isoformat(),
                minutes_to_event=round((latest-current).total_seconds()/60, 1),
                scenarios=_scenarios(recent_cluster[0]["category"]),
                forecast_risk="PRA-RILIS SELESAI",
                news_conclusion_status="WAITING_ACTUAL",
                news_conclusion="MENUNGGU ACTUAL RESMI — BELUM ADA BIAS XAU",
                news_conclusion_basis=(
                    "Rilis telah lewat; forecast-vs-previous tidak boleh dipakai "
                    "untuk menyimpulkan spike. Menunggu actual resmi dan konsensus numerik."
                ),
            )
            if not fresh(event_hb.get("observed_at"), current, 600) or (
                snapshot.get("publication_fresh") is False or
                not event_hb.get("healthy")
            ):
                result["news_conclusion"] = "DATA RILIS TERLAMBAT — TUNGGU UPDATE"
                result["news_conclusion_status"] = "STALE"
                return result
            verified: list[dict[str, Any]] = []
            official_components = 0
            preliminary_components = 0
            for e in recent_cluster:
                component = str(
                    e.get("event_component")
                    or canonical_event_key(str(e.get("title") or ""))
                )
                if _unpublished_oct_2026_cpi_yoy(e, latest):
                    result["unpublished_components"].append(component)
                    continue
                actual, forecast = number(e.get("actual")), number(e.get("forecast"))
                official = str(e.get("source_tier") or "").startswith("OFFICIAL_ACTUAL")
                corroborated = (
                    int(e.get("actual_source_count") or 0) >= 2
                    and str(e.get("source_agreement") or "") == "MULTI_SOURCE_AGREE"
                    and len(e.get("actual_quotes") or []) >= 2
                )
                provisional = (
                    int(e.get("actual_source_count") or 0) == 1
                    and int(e.get("forecast_source_count") or 0) >= 3
                    and str(e.get("source_agreement") or "") == "MULTI_SOURCE_AGREE"
                    and len(e.get("actual_quotes") or []) == 1
                )
                if (not (official or corroborated or provisional)
                        or actual is None or forecast is None or
                        _source_conflict(e) or
                        not _comparable_inflation_quote(component, actual, forecast)):
                    continue
                surprise = round(actual - forecast, 6)
                sign = 1 if surprise > 1e-9 else -1 if surprise < -1e-9 else 0
                if e["category"] in INVERSE:
                    sign *= -1
                row = {
                    "title": e.get("title"), "event_component": component,
                    "category": e["category"], "actual": actual,
                    "forecast": forecast, "previous": number(e.get("previous")),
                    "surprise": surprise, "hawkish_tilt": sign,
                    "source": e.get("source"),
                }
                verified.append(row)
                if official:
                    official_components += 1
                if provisional and not (official or corroborated):
                    preliminary_components += 1
            result["event_cluster"] = verified
            # CPI requires headline and core MoM; no fabricated October-2026 YoY.
            required = (
                {"CPI_MOM", "CORE_CPI_MOM"}
                if latest.date() == OCT_2026_CPI_RELEASE
                and any(e.get("category") == "CPI" for e in recent_cluster)
                else set()
            )
            complete = bool(verified) and (
                not required or required.issubset({
                    row["event_component"] for row in verified
                })
            )
            signs = {row["hawkish_tilt"] for row in verified} - {0}
            if verified:
                result["state"] = "POST_NEWS"
                result["news_conclusion_components"] = len(verified)
                preliminary = preliminary_components > 0
                result["news_conclusion_status"] = (
                    "PARTIAL_ACTUAL" if not complete else
                    "PROVISIONAL_ACTUAL_SINGLE_SOURCE" if preliminary else
                    "OFFICIAL_VERIFIED" if official_components == len(verified) else
                    "MULTI_SOURCE_CORROBORATED"
                )
                suffix = (
                    " (DATA AWAL — 1 SUMBER)" if preliminary else
                    "" if complete else " (ACTUAL PARSIAL)"
                )
                if signs == {1}:
                    result["news_conclusion"] = (
                        "HOT SURPRISE — BEARISH XAU" + suffix
                    )
                    if complete:
                        result["xau_bias"] = (
                            "BEARISH_XAU_PRELIMINARY" if preliminary else "BEARISH_XAU"
                        )
                elif signs == {-1}:
                    result["news_conclusion"] = (
                        "COOL SURPRISE — BULLISH XAU" + suffix
                    )
                    if complete:
                        result["xau_bias"] = (
                            "BULLISH_XAU_PRELIMINARY" if preliminary else "BULLISH_XAU"
                        )
                elif signs == {1, -1}:
                    result["news_conclusion"] = "MIXED SURPRISE — XAU NETRAL"
                    result["xau_bias"] = "NEUTRAL_MIXED"
                else:
                    result["news_conclusion"] = "INLINE ACTUAL — XAU NETRAL"
                    result["xau_bias"] = "NEUTRAL_MIXED"
                comparisons = ", ".join(
                    f'{row["event_component"]} {row["actual"]:.2f}% vs '
                    f'{row["forecast"]:.2f}% (Δ {row["surprise"]:+.2f}pp)'
                    for row in verified
                )
                provenance = (
                    "Actual awal dari satu sumber kalender; BELUM terverifikasi BLS" 
                    if preliminary else
                    "Actual resmi BLS" if official_components == len(verified) else
                    "Actual konsisten dari sedikitnya 2 kalender berbeda; "
                    "konfirmasi BLS otomatis belum tersedia"
                )
                result["news_conclusion_basis"] = (
                    provenance + ", dibandingkan forecast "
                    "pra-rilis: " + comparisons + ". "
                    + ("" if complete else "Komponen rilis belum lengkap. ")
                    + "Arah harga tetap perlu konfirmasi DXY, US2Y dan struktur."
                )
                result["conviction"] = "LOW_PROVISIONAL" if preliminary else "NEWS_ONLY"
                result["expectation"] = "POST_RELEASE_ACTUAL"
            return result
    if "CALENDAR_STALE_MISSING_OR_UNHEALTHY" in reasons:
        result["news_gate"] = "UNAVAILABLE_STALE_CALENDAR"
        result["news_gate_action"] = "UNAVAILABLE"
    if not upcoming:
        reasons.append("NO_UPCOMING_SUPPORTED_EVENT_IN_CALENDAR")
        result["news_conclusion"] = "TIDAK ADA NEWS USD PRIORITAS TERDEKAT"
        result["news_conclusion_basis"] = (
            "Tidak ada rilis USD yang memenuhi cakupan kalender saat ini; "
            "ini bukan bukti tidak ada peristiwa ekonomi."
        )
        return result
    at, event = upcoming[0]
    minutes = (at - current).total_seconds() / 60
    result.update(event=event, minutes_to_event=round(minutes, 1),
                  event_time_wib=at.astimezone(ZoneInfo("Asia/Jakarta")).isoformat(),
                  scenarios=_scenarios(event["category"]))
    # Evaluate all simultaneous components, e.g. headline/core CPI and NFP/wages.
    cluster = [e for t, e in upcoming if t == at]
    # Official BLS notice: Oct-2026 CPI annual headline/core values have no
    # Oct-2025 reference index. Never give calendar-only YoY forecasts a vote.
    result["unpublished_components"] = [
        str(e.get("event_component") or canonical_event_key(str(e.get("title") or "")))
        for e in cluster if _unpublished_oct_2026_cpi_yoy(e, at)
    ]
    cluster = [e for e in cluster if not _unpublished_oct_2026_cpi_yoy(e, at)]
    if not cluster:
        result["news_conclusion"] = "CPI YOY TIDAK DIRILIS — TUNGGU KOMPONEN BULANAN"
        result["news_conclusion_basis"] = (
            "BLS tidak menerbitkan headline/core CPI YoY Oktober 2026; "
            "forecast kalender YoY tidak dihitung sebagai bukti rilis."
        )
        return result
    # Official calendar schedule-only entries (without forecast) should not
    # veto a simultaneous measurable CPI/NFP/PPI release component. An event
    # with a partial numeric forecast still participates and requires quorum.
    measured = [e for e in cluster if number(e.get("forecast")) is not None]
    if measured:
        cluster = measured
    tilts = []
    provisional_tilts: list[int] = []
    quorum_counts: list[int] = []
    for e in cluster:
        forecast, previous = number(e.get("forecast")), number(e.get("previous"))
        conflict = _source_conflict(e)
        component = str(e.get("event_component") or canonical_event_key(str(e.get("title") or "")))
        if not _comparable_inflation_quote(component, forecast, previous):
            conflict = True
            reasons.append("UNIT_MISMATCH_EVENT:" + str(e.get("title")))
        # Verify the actual numeric rows, NOT the total number of calendar
        # sources. Official schedules do not publish independent forecasts.
        source_quotes: dict[str, dict[str, Any]] = {}
        invalid_sources: set[str] = set(str(x) for x in (e.get("rejected_quote_sources") or []))
        raw_quotes = e.get("forecast_quotes") or []
        if isinstance(raw_quotes, list):
            for quote in raw_quotes:
                if not isinstance(quote, dict):
                    continue
                provider = str(quote.get("source") or "").strip().upper()
                value = number(quote.get("forecast"))
                if provider not in SECONDARY_CONSENSUS_SOURCES or value is None:
                    continue
                quoted_previous = number(quote.get("previous"))
                if not _comparable_inflation_quote(component, value, quoted_previous):
                    invalid_sources.add(provider)
                    continue
                if provider in source_quotes and source_quotes[provider]["forecast"] != value:
                    conflict = True
                source_quotes[provider] = {
                    "source": provider, "forecast": value,
                    "previous": quoted_previous,
                }
        count = len(source_quotes)
        paired = sum(quote["previous"] is not None for quote in source_quotes.values())
        quorum_counts.append(paired)
        tilt = None
        if conflict:
            reasons.append("SOURCE_CONFLICT:" + str(e.get("title")))
        if paired < MIN_FORECAST_SOURCES:
            reasons.append(
                "FORECAST_QUORUM:" + str(e.get("title")) +
                f":{paired}/{MIN_FORECAST_SOURCES}"
            )
        if not conflict and paired >= MIN_FORECAST_SOURCES:
            if forecast is not None and previous is not None:
                tolerance = max(abs(previous) * 0.01, 1e-9)
                tilt = 0 if abs(forecast - previous) <= tolerance else (1 if forecast > previous else -1)
                if e["category"] in INVERSE:
                    tilt *= -1
            else:
                reasons.append("CONSENSUS_OR_PREVIOUS_MISSING:" + str(e.get("title")))
        if e["category"] == "FOMC":
            reasons.append("FOMC_LANGUAGE_AND_RATE_PATH_UNMODELED")
            tilt = None
        if tilt is not None:
            tilts.append(tilt)
        # A 2-source or incomplete-component indication is informational
        # ONLY, never labeled as a validated three-source consensus. Two
        # independent vendors must provide both forecast and previous.
        indicative = tilt
        if indicative is None and not conflict and count >= 2 and paired >= 2 and forecast is not None and previous is not None and e["category"] != "FOMC":
            tolerance = max(abs(previous) * 0.01, 1e-9)
            indicative = 0 if abs(forecast - previous) <= tolerance else (1 if forecast > previous else -1)
            if e["category"] in INVERSE:
                indicative *= -1
        if indicative is not None:
            provisional_tilts.append(indicative)
        result["event_cluster"].append({
            "title": e.get("title"), "category": e["category"],
            "event_component": e.get("event_component"),
            "forecast": forecast, "previous": previous, "hawkish_tilt": tilt,
            "indicative_hawkish_tilt": indicative,
            "source_count": e.get("source_count", 1),
            "sources": e.get("sources") or [e.get("source")],
            "forecast_source_count": count,
            "forecast_pair_count": paired,
            "rejected_quote_sources": sorted(invalid_sources),
            "forecast_sources": sorted(source_quotes),
            "forecast_quotes": [source_quotes[p] for p in sorted(source_quotes)],
            "source_agreement": e.get("source_agreement") or "SINGLE_SOURCE",
            "source_confidence": e.get("source_confidence") or "LOW",
            "conflicts": e.get("conflicts") or [],
        })
    result["forecast_quorum_met"] = (
        bool(cluster) and all(count >= MIN_FORECAST_SOURCES for count in quorum_counts)
    )
    calendar_valid = not any(
        reason in reasons
        for reason in ("PUBLICATION_STALE", "CALENDAR_STALE_MISSING_OR_UNHEALTHY")
    )
    if not calendar_valid:
        result["news_conclusion"] = "DATA KALENDER TERLAMBAT — TUNGGU UPDATE"
        result["news_conclusion_status"] = "STALE"
        result["news_conclusion_basis"] = (
            "Tidak mengeluarkan bias arah dari kalender yang tidak segar."
        )
    elif provisional_tilts:
        signed = set(provisional_tilts) - {0}
        incomplete = len(tilts) != len(cluster)
        if signed == {1, -1}:
            result["news_conclusion"] = "MIXED RISK — XAU TIDAK ADA BIAS DOMINAN"
            result["news_conclusion_status"] = "MIXED"
            result["news_conclusion_basis"] = (
                "Komponen rilis menunjukkan implikasi hawkish dan dovish bersamaan. "
                "Tunggu actual versus forecast dan respons DXY/yield."
            )
            # Two independently verified CPI monthly components can establish a
            # *qualified* directional lean even if unverified YoY estimates
            # disagree. Keep MIXED status and the strict overall quorum.
            monthly = [
                row for row in result["event_cluster"]
                if row.get("event_component") in {"CPI_MOM", "CORE_CPI_MOM"}
                and row.get("forecast_pair_count", 0) >= MIN_FORECAST_SOURCES
            ]
            opposed = [
                row for row in result["event_cluster"]
                if row.get("indicative_hawkish_tilt") == 1
            ]
            if (
                len(monthly) == 2
                and all(row.get("indicative_hawkish_tilt") == -1 for row in monthly)
                and opposed
                and all(
                    row.get("event_component") in {"CPI_YOY", "CORE_CPI_YOY"}
                    and row.get("forecast_pair_count", 0) < MIN_FORECAST_SOURCES
                    for row in opposed
                )
            ):
                result["news_conclusion"] = "MIXED — MOM COOL LEAN (BELUM TERVERIFIKASI PENUH)"
                result["news_conclusion_basis"] = (
                    "Headline dan Core CPI bulanan sama-sama menunjukkan perlambatan "
                    "dengan minimal 3 pasangan forecast/previous; estimasi tahunan "
                    "justru HOT tetapi belum memenuhi quorum. "
                    "COOL hanya indikasi komponen bulanan, bukan arah XAU "
                    "terkonfirmasi atau izin entry."
                )
        else:
            pressure = next(iter(signed)) if signed else 0
            label = (
                "HOT RISK — BEARISH XAU" if pressure == 1 else
                "COOL RISK — BULLISH XAU" if pressure == -1 else
                "INLINE — XAU NETRAL"
            )
            validated = bool(tilts) and not incomplete
            result["news_conclusion_status"] = "VALIDATED" if validated else "PROVISIONAL"
            result["news_conclusion"] = (
                label + (" (PRA-RILIS)" if validated else " (INDIKASI SEMENTARA)")
            )
            result["news_conclusion_components"] = len(provisional_tilts)
            result["news_conclusion_basis"] = (
                f"{len(provisional_tilts)} komponen memiliki perbandingan forecast/previous "
                f"dari minimal 2 penyedia. " +
                ("Semua komponen memenuhi quorum 3 sumber." if validated else
                 "Belum semua komponen memenuhi quorum 3 sumber atau bebas konflik; "
                 "kesimpulan bukan sinyal entry.")
            )
    else:
        any_conflict = any(_source_conflict(e) for e in cluster)
        result["news_conclusion"] = (
            "DATA KONFLIK — XAU BELUM ADA BIAS" if any_conflict else
            "FORECAST BELUM CUKUP — XAU BELUM ADA BIAS"
        )
        result["news_conclusion_basis"] = (
            "Tidak ditemukan sedikitnya dua forecast lengkap yang searah dan bebas "
            "konflik untuk rilis ini. Kesimpulan arah ditahan."
        )
    if tilts and len(tilts) == len(cluster) and calendar_valid:
        if 1 in tilts and -1 in tilts:
            expectation = "MIXED"
        elif 1 in tilts:
            expectation = "HOT-RISK"
        elif -1 in tilts:
            expectation = "COOL"
        else:
            expectation = "INLINE"
        result["expectation"] = expectation
        result["forecast_risk"] = {
            "HOT-RISK": "HOT RISK (BEARISH XAU)",
            "COOL": "COOL RISK (BULLISH XAU)",
            "INLINE": "INLINE (NEUTRAL XAU)",
            "MIXED": "MIXED (NEUTRAL XAU)",
        }[expectation]
        result["forecast_xau_bias"] = {
            "HOT-RISK": "BEARISH_XAU",
            "COOL": "BULLISH_XAU",
            "INLINE": "NEUTRAL_MIXED",
            "MIXED": "NEUTRAL_MIXED",
        }[expectation]
    components = macro.get("components") or {}
    cross = macro_details.get("cross_asset") or {}
    intraday_dxy = macro.get("dxy_intraday") or macro_details.get("dxy_intraday") or {}
    for name in ("DXY", "US2Y", "US10Y", "REAL_YIELD_10Y"):
        row = intraday_dxy if name == "DXY" else (cross.get(name) or components.get(name) or {})
        intraday = name == "DXY"
        observed = row.get("current_at") if intraday else row.get("observed_at")
        dxy_limit = 900 if str(row.get("source") or "").startswith("CTRADER_") else 1800
        valid = (fresh(observed, current, dxy_limit if intraday else 7 * 86400)
                 and row.get("freshness") == "FRESH")
        delta = number(row.get("net_pct") if intraday else row.get("delta"))
        valid = valid and delta is not None
        if not valid:
            reasons.append(name + "_STALE_OR_MISSING")
            if name == "DXY" and row.get("source_status") == "RATE_LIMITED":
                reasons.append("DXY_PROVIDER_RATE_LIMITED")
        threshold = 0.05 if intraday else 2.0
        pressure = None if not valid else (1 if delta >= threshold else -1 if delta <= -threshold else 0)
        result["components"].append({"name": name, "fresh": valid, "observed_at": observed,
                                      "current": number(row.get("current")),
                                      "basis": row.get("basis"),
                                      "delta": delta, "unit": "%" if intraday else "bps",
                                      "frequency": "INTRADAY" if intraday else "DAILY_REGIME",
                                      "source": row.get("source") or row.get("provider"),
                                      "source_status": row.get("source_status") or row.get("freshness"),
                                      "hawkish_pressure": pressure})
    if reasons:
        result["expectation"] = "UNAVAILABLE"
        return result
    result["state"] = "PRE_NEWS"
    pressures = [r["hawkish_pressure"] for r in result["components"]]
    expectation = result["expectation"]
    expected = 1 if expectation == "HOT-RISK" else -1 if expectation == "COOL" else 0
    conflict = (1 in pressures and -1 in pressures) or (expected and -expected in pressures)
    direction = expected if expected and not conflict else 0
    result["xau_bias"] = "BEARISH_XAU" if direction == 1 else "BULLISH_XAU" if direction == -1 else "NEUTRAL_MIXED"
    result["conviction"] = "LOW" if not direction else "MEDIUM" if pressures.count(direction) >= 3 else "LOW"
    if conflict:
        reasons.append("CONSENSUS_MACRO_DIVERGENCE")
        # Primary headline must not advertise a bullish spike while fresh
        # DXY/yield evidence contradicts a declining CPI consensus.
        if expected == -1:
            result["news_conclusion"] = (
                "MIXED — COOL FORECAST vs HAWKISH MACRO; RISIKO HOT SURPRISE"
            )
            result["news_conclusion_status"] = "MACRO_DIVERGENCE"
            result["news_conclusion_basis"] = (
                "Forecast lebih rendah dari previous bukan actual dan bukan "
                "prediksi spike bullish. Makro segar bertentangan; tahan arah."
            )
    result["next_step"] = "H1 bias → M15 struktur/reversal → M5 timing; cek revisi dan respons yield/DXY setelah rilis."
    return result
