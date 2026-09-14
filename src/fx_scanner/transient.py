from __future__ import annotations


TRANSIENT_RETRY_DELAYS = (0.0, 0.5, 1.0)
_TRANSIENT_STATUS_CODES = frozenset({"408", "429", "502", "503", "504"})
_TRANSIENT_MARKERS = (
    "gateway timeout",
    "bad gateway",
    "service unavailable",
    "too many requests",
    "rate limit",
    "timed out",
    "timeout",
    "connection reset",
    "connection aborted",
    "connection refused",
    "temporarily unavailable",
    "server disconnected",
)


def is_transient_backend_error(exc: BaseException) -> bool:
    """Return True only for bounded-retry backend/transport failures.

    The classifier walks chained exceptions because storage adapters deliberately
    wrap transport failures in domain exceptions. Authentication, configuration,
    decryption, validation, and ambiguous-state errors are not classified as
    transient and therefore remain immediate fail-closed failures.
    """
    current: BaseException | None = exc
    seen: set[int] = set()
    for _ in range(6):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))

        for attr in ("code", "status_code", "status"):
            raw = getattr(current, attr, None)
            if raw is not None and str(raw).strip() in _TRANSIENT_STATUS_CODES:
                return True

        text = f"{type(current).__name__}: {current}".lower()
        if any(marker in text for marker in _TRANSIENT_MARKERS):
            return True

        current = current.__cause__ or current.__context__
    return False
