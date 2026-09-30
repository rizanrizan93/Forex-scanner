from __future__ import annotations

import re


_TRANSIENT_STATUS = {"408", "502", "503", "504", "522", "524"}


def is_transient_supabase_unavailable(exc: BaseException) -> bool:
    """Recognize transport/5xx Supabase/PostgREST outages through wrapped causes.

    Schema, permission, and application errors are deliberately not swallowed.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    for _ in range(6):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        if _direct_transient(current):
            return True
        current = current.__cause__
    return False


def _direct_transient(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True

    code = str(getattr(exc, "code", "") or "")
    if code in _TRANSIENT_STATUS:
        return True

    arg0 = exc.args[0] if exc.args else None
    if isinstance(arg0, dict) and str(arg0.get("code") or "") in _TRANSIENT_STATUS:
        return True

    cls = type(exc)
    if cls.__module__.startswith("postgrest") and cls.__name__ == "APIError":
        return bool(
            re.search(
                r"['\"]code['\"]:\s*['\"]?(?:408|502|503|504|522|524)\b",
                str(exc)[:800],
            )
        )

    return cls.__module__.startswith(("httpx", "httpcore")) and (
        "Timeout" in cls.__name__ or "ConnectError" in cls.__name__
    )
