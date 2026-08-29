from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from ..exceptions import MissingOptionalDependency
from ..models import Bar, Tick


class ParquetStore:
    """Partitioned Parquet storage for market-data history."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    @staticmethod
    def _deps():
        try:
            import pandas as pd
            import pyarrow  # noqa: F401
        except ModuleNotFoundError as exc:
            raise MissingOptionalDependency("pandas + pyarrow are required for ParquetStore") from exc
        return pd

    def write_ticks(self, ticks: list[Tick]) -> list[Path]:
        if not ticks:
            return []
        pd = self._deps()
        by_partition: dict[tuple[str, str], list[Tick]] = {}
        for tick in ticks:
            key = (tick.symbol, tick.timestamp.date().isoformat())
            by_partition.setdefault(key, []).append(tick)

        paths: list[Path] = []
        for (symbol, date), rows in by_partition.items():
            path = self.root / "ticks" / f"symbol={symbol}" / f"date={date}" / f"part-{uuid4().hex}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            frame = pd.DataFrame([asdict(x) for x in rows])
            frame.to_parquet(path, index=False, engine="pyarrow", compression="zstd")
            paths.append(path)
        return paths

    def write_bars(self, bars: list[Bar]) -> list[Path]:
        if not bars:
            return []
        pd = self._deps()
        by_partition: dict[tuple[str, str, str], list[Bar]] = {}
        for bar in bars:
            key = (bar.timeframe, bar.symbol, bar.timestamp.date().isoformat())
            by_partition.setdefault(key, []).append(bar)

        paths: list[Path] = []
        for (tf, symbol, date), rows in by_partition.items():
            path = self.root / "bars" / f"timeframe={tf}" / f"symbol={symbol}" / f"date={date}" / f"part-{uuid4().hex}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            frame = pd.DataFrame([asdict(x) for x in rows])
            frame.to_parquet(path, index=False, engine="pyarrow", compression="zstd")
            paths.append(path)
        return paths
