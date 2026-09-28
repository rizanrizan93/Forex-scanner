from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .xau_standalone_ctrader_v253 import (
    build_standalone_ctrader_feed,
    collect_standalone_xau_snapshot,
)


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def _json_default(value: Any):
    if isinstance(value, datetime):
        return value.isoformat()
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _previous_dom(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload.get("dom_analysis") or {})


def write_snapshot(output: Path) -> dict[str, Any]:
    account_raw = os.getenv("CTRADER_ACCOUNT_ID", "").strip()
    feed = build_standalone_ctrader_feed(
        client_id=_required("CTRADER_CLIENT_ID"),
        client_secret=_required("CTRADER_CLIENT_SECRET"),
        access_token=_required("CTRADER_ACCESS_TOKEN"),
        refresh_token=os.getenv("CTRADER_REFRESH_TOKEN", "").strip() or None,
        trader_login=int(_required("CTRADER_TRADER_LOGIN")),
        account_id=int(account_raw) if account_raw else None,
    )
    try:
        state = collect_standalone_xau_snapshot(
            feed,
            root=Path(__file__).resolve().parents[2],
            previous_dom_analysis=_previous_dom(output),
        )
    finally:
        try:
            feed.close()
        except Exception:
            pass

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(state, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="runtime/xau_standalone_snapshot.json",
    )
    args = parser.parse_args(argv)
    output = Path(args.output)
    state = write_snapshot(output)
    canonical = dict(state.get("canonical") or {})
    pressure = dict(state.get("pressure_transition") or {})
    print(
        "RIZAN_STANDALONE_V253 "
        f"state={state.get('state')} "
        f"direction={canonical.get('direction') or 'WAIT'} "
        f"price={dict(state.get('quote') or {}).get('mid')} "
        f"pressure={pressure.get('state') or 'UNAVAILABLE'} "
        "execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
