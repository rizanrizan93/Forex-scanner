"""Strict wire timestamps: offsets required; UTC is the internal representation."""
from datetime import datetime, timezone
import re

_OFFSET = re.compile(r"(?:Z|[+-]\d{2}:\d{2})$", re.IGNORECASE)
_NAMES = {"timestamp", "ts", "event_time", "generated_at", "created_at", "server_time",
          "signal_time", "bar_time", "observed_at", "xauday"}


def parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not _OFFSET.search(value):
        raise ValueError("TIMESTAMP_OFFSET_REQUIRED")
    try:
        at = datetime.fromisoformat(value[:-1] + "+00:00" if value[-1:].upper() == "Z" else value)
        if at.utcoffset() is None:
            raise ValueError("TIMESTAMP_OFFSET_REQUIRED")
        return at.astimezone(timezone.utc)
    except (TypeError, ValueError) as exc:
        raise ValueError("TIMESTAMP_INVALID") from exc


def utc_text(value: datetime) -> str:
    if value.utcoffset() is None:
        raise ValueError("TIMESTAMP_OFFSET_REQUIRED")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def validate_timestamps(payload) -> None:
    """Validate nested checkpoints/snapshots without rewriting durable state bytes."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.lower().endswith("utc") or key.lower() in _NAMES:
                parse_utc(value)
            else:
                validate_timestamps(value)
    elif isinstance(payload, list):
        for value in payload:
            validate_timestamps(value)

