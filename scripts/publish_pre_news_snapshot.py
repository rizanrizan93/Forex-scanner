"""Publish only bounded calendar/macro context; never loads broker execution."""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fx_scanner.demo_xau_event_risk_v193 import build_dashboard_projection as event_projection
from fx_scanner.demo_xau_macro_attribution_v357 import build_dashboard_projection as macro_projection
from fx_scanner.pre_news_expectation import EVENT_WORKER, MACRO_WORKER
from fx_scanner.pre_news_transport import CONTRACT, MAX_BYTES
from fx_scanner.dxy_broker_context import select_dxy


def _safe_source_status(value):
    """Publish bounded provider health without upstream error text or credentials."""
    text = str(value or "UNKNOWN")
    parts = text.split(":")
    if parts[0] == "OK":
        return ":".join(parts[:2]) if len(parts) > 1 else "OK"
    if parts[0] == "ERROR":
        return "ERROR:" + (parts[1] if len(parts) > 1 else "UNKNOWN")
    if text in {"DISABLED", "UNKNOWN"}:
        return text
    return text[:48]


def _safe_fusion_policy(value):
    policy = dict(value or {})
    allowed = (
        "identity",
        "numeric",
        "official_actual_precedence",
        "source_conflict_abstains",
        "secondary_fail_open",
    )
    return {key: policy.get(key) for key in allowed if key in policy}


def build_snapshot(client, *, now, broker_dxy=None):
    rows = []
    for name in (EVENT_WORKER, MACRO_WORKER):
        response = (client.table("runtime_heartbeats").select("worker_name,observed_at,healthy,details")
                    .eq("worker_name", name).order("observed_at", desc=True).limit(1).execute())
        if not response.data:
            continue
        row = response.data[0]
        details = row.get("details") or {}
        if name == EVENT_WORKER:
            risk = details.get("risk") or details.get("dashboard_projection") or {}
            context = {
                "risk": event_projection(risk),
                "calendar_fusion_version": str(details.get("calendar_fusion_version") or "V192"),
                "source_status": {
                    str(key): _safe_source_status(value)
                    for key, value in dict(details.get("source_status") or {}).items()
                },
                "fusion_policy": _safe_fusion_policy(details.get("fusion_policy")),
            }
        else:
            evaluation = details.get("evaluation") or {}
            projection = macro_projection(evaluation)
            dxy = evaluation.get("dxy_intraday") or details.get("dxy_intraday") or {}
            dxy = select_dxy(dxy, broker_dxy or {}, now=now)
            projection["dxy_intraday"] = {key: dxy.get(key) for key in (
                "current_at", "reference_at", "freshness", "available", "net_pct", "source",
                "current", "reference", "basis", "symbol", "frequency", "source_status")}
            error = str(dxy.get("error") or "")
            projection["dxy_intraday"]["source_status"] = (
                "RATE_LIMITED" if "429" in error else "SOURCE_ERROR" if error else
                "OK" if dxy.get("available") else "STALE_OR_MISSING")
            context = {"evaluation": projection}
        rows.append({"worker_name": name, "observed_at": row.get("observed_at"),
                     "healthy": row.get("healthy") is True, "details": context})
    return {"contract": CONTRACT, "published_at": now.isoformat(), "heartbeats": rows,
            "execution_authority": False, "execution_influence": False}


def main():
    from fx_scanner.storage.backend import create_backend_client
    broker = {}
    if len(sys.argv) > 2 and Path(sys.argv[2]).is_file():
        broker = json.loads(Path(sys.argv[2]).read_text())
    result = build_snapshot(create_backend_client(), now=datetime.now(UTC), broker_dxy=broker)
    raw = json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
    if len(raw) > MAX_BYTES:
        raise ValueError("pre-news snapshot too large")
    path = Path(sys.argv[1])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    print("PRE_NEWS_SNAPSHOT workers=" + str(len(result["heartbeats"])))


if __name__ == "__main__":
    main()
