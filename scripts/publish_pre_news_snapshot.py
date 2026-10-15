"""Publish only bounded calendar/macro context; never loads broker execution."""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fx_scanner.demo_xau_event_risk_v192 import build_dashboard_projection as event_projection
from fx_scanner.demo_xau_macro_attribution_v357 import build_dashboard_projection as macro_projection
from fx_scanner.pre_news_expectation import EVENT_WORKER, MACRO_WORKER
from fx_scanner.pre_news_transport import CONTRACT, MAX_BYTES


def build_snapshot(client, *, now):
    rows = []
    for name in (EVENT_WORKER, MACRO_WORKER):
        response = (client.table("runtime_heartbeats").select("worker_name,observed_at,healthy,details")
                    .eq("worker_name", name).order("observed_at", desc=True).limit(1).execute())
        if not response.data:
            continue
        row = response.data[0]
        details = row.get("details") or {}
        if name == EVENT_WORKER:
            context = {"risk": event_projection(details.get("risk") or {})}
        else:
            evaluation = details.get("evaluation") or {}
            projection = macro_projection(evaluation)
            dxy = evaluation.get("dxy_intraday") or details.get("dxy_intraday") or {}
            projection["dxy_intraday"] = {key: dxy.get(key) for key in (
                "current_at", "reference_at", "freshness", "available", "net_pct", "source")}
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
    result = build_snapshot(create_backend_client(), now=datetime.now(UTC))
    raw = json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
    if len(raw) > MAX_BYTES:
        raise ValueError("pre-news snapshot too large")
    path = Path(sys.argv[1])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    print("PRE_NEWS_SNAPSHOT workers=" + str(len(result["heartbeats"])))


if __name__ == "__main__":
    main()
