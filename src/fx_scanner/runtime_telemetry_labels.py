"""Presentation-only classification of archived DB heartbeats.

This module does not query brokers, alter checkpoints, or affect trading.
A historical cbot_bridge_* row must never be represented as current LIVE health.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

LEGACY_CBOT_BRIDGE_WORKERS = frozenset({
    "cbot_bridge_xauusd",
    "cbot_bridge_eurusd",
    "cbot_bridge_btcusd",
})
LEGACY_FRESH_SECONDS = 15 * 60
HISTORICAL_SECONDS = 24 * 60 * 60


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(UTC)


def annotate_heartbeat_rows(
    rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Copy rows and label age/origin without changing recorded healthy values."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("now must have a timezone")
    current = current.astimezone(UTC)
    result = []
    for raw in rows:
        row = dict(raw)
        worker = str(row.get("worker_name") or "")
        old_bridge = worker in LEGACY_CBOT_BRIDGE_WORKERS
        observed = _parse_time(row.get("observed_at"))
        age = None if observed is None else (current - observed).total_seconds()
        row["telemetry_origin"] = (
            "ARSIP BRIDGE DB (bukan verifikasi LIVE)"
            if old_bridge else "HEARTBEAT WORKER DATABASE"
        )
        row["telemetry_age_minutes"] = (
            None if age is None or age < -30 else round(max(age, 0) / 60, 1)
        )
        if age is None or age < -30:
            status = "WAKTU TIDAK VALID"
        elif old_bridge:
            status = (
                "ARSIP / BELUM TERVERIFIKASI LIVE"
                if age > LEGACY_FRESH_SECONDS
                else "RECORD BARU / KONEKSI LIVE BELUM TERVERIFIKASI"
            )
        elif age > HISTORICAL_SECONDS:
            status = "DATA HISTORIS (bukan status kini)"
        else:
            status = "RECORDED (bukan bukti koneksi broker LIVE)"
        row["telemetry_interpretation"] = status
        result.append(row)
    return result
