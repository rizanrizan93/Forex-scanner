from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .exceptions import ConfigurationError


@dataclass(frozen=True, slots=True)
class PairSpec:
    symbol: str
    base: str
    quote: str
    pip_size: float
    tier: str


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    pairs: tuple[PairSpec, ...]
    timeframes: dict[str, int]
    risk: dict[str, Any]
    scoring: dict[str, Any]
    sessions: dict[str, Any]

    @property
    def pair_map(self) -> dict[str, PairSpec]:
        return {p.symbol: p for p in self.pairs}


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigurationError(f"{path} must contain a YAML mapping")
    return data


def load_project_config(root: str | Path | None = None) -> ProjectConfig:
    root_path = Path(root) if root else Path(__file__).resolve().parents[2]
    cfg = root_path / "config"

    pair_data = _read_yaml(cfg / "pairs.yaml")
    raw_pairs = pair_data.get("pairs", [])
    if len(raw_pairs) != 15:
        raise ConfigurationError(f"v0.1 requires exactly 15 configured pairs, got {len(raw_pairs)}")

    pairs: list[PairSpec] = []
    seen: set[str] = set()
    for item in raw_pairs:
        symbol = str(item["symbol"]).upper()
        base = str(item["base"]).upper()
        quote = str(item["quote"]).upper()
        if symbol != base + quote:
            raise ConfigurationError(f"symbol/base/quote mismatch for {symbol}")
        if symbol in seen:
            raise ConfigurationError(f"duplicate pair {symbol}")
        seen.add(symbol)
        pip_size = float(item["pip_size"])
        if pip_size <= 0:
            raise ConfigurationError(f"invalid pip size for {symbol}")
        pairs.append(PairSpec(symbol, base, quote, pip_size, str(item["tier"]).upper()))

    timeframes = {str(k).upper(): int(v) for k, v in pair_data.get("timeframes", {}).items()}
    required_tfs = {"M1", "M5", "M15", "H1", "H4", "D1"}
    if set(timeframes) != required_tfs:
        raise ConfigurationError(f"timeframes must be exactly {sorted(required_tfs)}")
    if any(v <= 0 for v in timeframes.values()):
        raise ConfigurationError("timeframe seconds must be positive")

    risk = _read_yaml(cfg / "risk.yaml")
    scoring = _read_yaml(cfg / "scoring.yaml")
    sessions = _read_yaml(cfg / "sessions.yaml")

    pair_weight_sum = sum(scoring["pair_opportunity"].values())
    exec_weight_sum = sum(scoring["execution_conviction"].values())
    if pair_weight_sum != 100 or exec_weight_sum != 100:
        raise ConfigurationError("scoring weights must sum to 100")

    acceptance = risk.get("acceptance", {})
    if float(acceptance.get("oos_win_rate_min", 0)) < 0.55:
        raise ConfigurationError("OOS win-rate gate cannot be below 55%")
    if float(acceptance.get("profit_factor_min", 0)) < 1.30:
        raise ConfigurationError("profit-factor gate cannot be below 1.30")

    return ProjectConfig(tuple(pairs), timeframes, risk, scoring, sessions)
