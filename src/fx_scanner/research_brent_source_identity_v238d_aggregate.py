from __future__ import annotations

import json
import os
from pathlib import Path
from statistics import median
from typing import Any

RESEARCH_VERSION = "BRENT_SOURCE_IDENTITY_V238D_1"


def _shard_dir() -> Path:
    path = Path(os.getenv("BRENT_V238D_SHARD_DIR", "/tmp/brent-v238d-shards").strip())
    if not path.exists():
        raise SystemExit(f"BRENT_V238D_SHARD_DIR_NOT_FOUND:{path}")
    return path


def _output_path() -> Path:
    return Path(
        os.getenv(
            "BRENT_V238D_FULL_OUTPUT",
            "artifacts/brent-source-identity-v238d-full.json",
        ).strip()
    )


def _load_shards(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for file in sorted(path.rglob("brent-cash-parity-v238d-*.json")):
        payload = dict(json.loads(file.read_text()) or {})
        if payload.get("window"):
            rows.append(payload)
    rows.sort(key=lambda row: tuple(row["window"]))
    return rows


def _best(row: dict[str, Any], symbol: str) -> dict[str, Any]:
    return dict(
        dict(dict(row.get("parity") or {}).get("lag_adjusted") or {})
        .get(symbol, {})
        .get("best")
        or {}
    )


def aggregate_identity(shards: list[dict[str, Any]]) -> dict[str, Any]:
    if not shards:
        raise ValueError("BRENT_V238D_NO_SHARDS")
    mappings = [row.get("preferred_historical_broker_symbol") for row in shards]
    all_pass = all(bool(row.get("identity_parity_pass")) for row in shards)
    consensus = (
        str(mappings[0])
        if all_pass and mappings[0] and all(value == mappings[0] for value in mappings)
        else None
    )

    windows: list[dict[str, Any]] = []
    for row in shards:
        xbr = _best(row, "XBRUSD")
        brent = _best(row, "BRENT")
        windows.append(
            {
                "window": row.get("window"),
                "preferred": row.get("preferred_historical_broker_symbol"),
                "identity_parity_pass": bool(row.get("identity_parity_pass")),
                "XBRUSD": {
                    "best_lag_hours": xbr.get("lag_hours"),
                    "return_corr": xbr.get("return_corr"),
                    "median_abs_pct": xbr.get("median_abs_pct"),
                    "median_abs_basis_usd": xbr.get("median_abs_basis_usd"),
                    "overlap": xbr.get("overlap"),
                },
                "BRENT": {
                    "best_lag_hours": brent.get("lag_hours"),
                    "return_corr": brent.get("return_corr"),
                    "median_abs_pct": brent.get("median_abs_pct"),
                    "median_abs_basis_usd": brent.get("median_abs_basis_usd"),
                    "overlap": brent.get("overlap"),
                },
            }
        )

    def _median_metric(symbol: str, metric: str) -> float | None:
        values = [
            float(item[symbol][metric])
            for item in windows
            if item[symbol].get(metric) is not None
        ]
        return None if not values else float(median(values))

    return {
        "artifact_contract": "BRENT_SOURCE_IDENTITY_V238D_1_EVIDENCE_1",
        "research_version": RESEARCH_VERSION,
        "window_count": len(shards),
        "all_windows_pass": all_pass,
        "consensus_symbol": consensus,
        "mapping_status": "SHADOW_REFERENCE" if consensus else "UNRESOLVED",
        "windows": windows,
        "cross_window": {
            "XBRUSD": {
                "median_return_corr": _median_metric("XBRUSD", "return_corr"),
                "median_abs_pct": _median_metric("XBRUSD", "median_abs_pct"),
                "median_abs_basis_usd": _median_metric(
                    "XBRUSD", "median_abs_basis_usd"
                ),
            },
            "BRENT": {
                "median_return_corr": _median_metric("BRENT", "return_corr"),
                "median_abs_pct": _median_metric("BRENT", "median_abs_pct"),
                "median_abs_basis_usd": _median_metric(
                    "BRENT", "median_abs_basis_usd"
                ),
            },
        },
        "interpretation": (
            "Consensus requires every independently tested historical window to pass "
            "its lag-adjusted identity gate and select the same FP Markets symbol. "
            "The result remains a shadow historical-source mapping only."
        ),
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "live_execution_enabled": False,
    }


def run() -> int:
    payload = aggregate_identity(_load_shards(_shard_dir()))
    output = _output_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(
        "BRENT_SOURCE_IDENTITY_V238D "
        f"windows={payload['window_count']} all_pass={int(payload['all_windows_pass'])} "
        f"consensus={payload['consensus_symbol'] or 'UNRESOLVED'} execution_authority=0"
    )
    if payload["consensus_symbol"] is None:
        raise SystemExit("BRENT_V238D_CROSS_WINDOW_CONSENSUS_FAILED")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
