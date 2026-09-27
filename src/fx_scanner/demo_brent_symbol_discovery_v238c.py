from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from .execution.ctrader_session import normalize_symbol_name
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy

RESEARCH_VERSION = "BRENT_BROKER_SYMBOL_V238C_1"
REFERENCE_SYMBOL = "XAUUSD"


def _candidate_score(normalized: str) -> int:
    value = normalize_symbol_name(normalized)
    if "BRENT" in value:
        return 100
    if value.startswith("XBR") or "XBRUSD" in value:
        return 95
    if value.startswith("BCO") or "BCOUSD" in value:
        return 90
    if "UKOIL" in value:
        return 85
    if value.startswith("BRN") or "BRN" in value:
        return 65
    if "OIL" in value:
        return 25
    return 0


def rank_brent_candidates(
    catalogue: Sequence[tuple[int, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol_id, raw_name in catalogue:
        normalized = normalize_symbol_name(raw_name)
        score = _candidate_score(normalized)
        if score <= 0:
            continue
        rows.append(
            {
                "symbol_id": int(symbol_id),
                "symbol_name": str(raw_name),
                "normalized_name": normalized,
                "score": int(score),
            }
        )
    rows.sort(
        key=lambda row: (
            -int(row["score"]),
            str(row["normalized_name"]),
            int(row["symbol_id"]),
        )
    )
    return rows


def resolve_unique_brent_candidate(
    candidates: Sequence[dict[str, Any]],
) -> dict[str, Any] | None:
    if not candidates:
        return None
    top = dict(candidates[0])
    if int(top.get("score") or 0) < 80:
        return None
    if len(candidates) > 1 and int(candidates[1].get("score") or 0) == int(
        top["score"]
    ):
        return None
    return top


def _output_path() -> Path:
    raw = os.getenv(
        "BRENT_V238C_OUTPUT",
        "artifacts/brent-broker-symbol-v238c.json",
    ).strip()
    if not raw:
        raise SystemExit("BRENT_V238C_OUTPUT_REQUIRED")
    return Path(raw)


def _catalogue_fingerprint(catalogue: Sequence[tuple[int, str]]) -> str:
    raw = "\n".join(
        f"{int(symbol_id)}|{str(symbol_name)}"
        for symbol_id, symbol_name in catalogue
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def run() -> int:
    policy = load_execution_policy(None)
    environment = str(policy.ctrader.get("environment", "")).upper()
    if environment != "DEMO":
        raise SystemExit("BRENT_V238C_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("BRENT_V238C_REQUIRE_DEMO")

    feed = build_ctrader_research_feed(policy, (REFERENCE_SYMBOL,))
    try:
        catalogue = feed.symbol_catalogue()
    finally:
        feed.close()

    candidates = rank_brent_candidates(catalogue)
    resolved = resolve_unique_brent_candidate(candidates)
    payload = {
        "artifact_contract": "BRENT_BROKER_SYMBOL_V238C_1_EVIDENCE_1",
        "research_version": RESEARCH_VERSION,
        "observed_at": datetime.now(tz=UTC).isoformat(),
        "broker": "FP Markets",
        "environment": "DEMO",
        "reference_symbol": REFERENCE_SYMBOL,
        "catalogue_size": len(catalogue),
        "catalogue_sha256": _catalogue_fingerprint(catalogue),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "resolved": resolved is not None,
        "resolved_symbol": None if resolved is None else resolved["symbol_name"],
        "resolved_symbol_id": None if resolved is None else resolved["symbol_id"],
        "interpretation": (
            "Read-only cTrader SymbolsList discovery. The result does not subscribe "
            "to the Brent candidate and does not create, modify, or authorize orders."
        ),
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "live_execution_enabled": False,
    }
    output = _output_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    names = ",".join(str(row["symbol_name"]) for row in candidates[:10]) or "NONE"
    print(
        "BRENT_BROKER_SYMBOL_V238C "
        f"catalogue={len(catalogue)} candidates={len(candidates)} "
        f"resolved={int(resolved is not None)} "
        f"symbol={payload['resolved_symbol'] or 'UNRESOLVED'} candidates_top={names} "
        "execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
