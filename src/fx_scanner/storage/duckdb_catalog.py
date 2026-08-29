from __future__ import annotations

from pathlib import Path

from ..exceptions import MissingOptionalDependency


class DuckDBCatalog:
    def __init__(self, database: str | Path = ":memory:"):
        try:
            import duckdb
        except ModuleNotFoundError as exc:
            raise MissingOptionalDependency("duckdb is required for DuckDBCatalog") from exc
        self._duckdb = duckdb
        self.connection = duckdb.connect(str(database))

    def register_data_lake(self, root: str | Path) -> None:
        root = Path(root).resolve()
        ticks_glob = str(root / "ticks" / "symbol=*" / "date=*" / "*.parquet").replace("'", "''")
        bars_glob = str(root / "bars" / "timeframe=*" / "symbol=*" / "date=*" / "*.parquet").replace("'", "''")
        self.connection.execute(
            f"CREATE OR REPLACE VIEW fx_ticks AS SELECT * FROM read_parquet('{ticks_glob}', hive_partitioning=true, union_by_name=true)"
        )
        self.connection.execute(
            f"CREATE OR REPLACE VIEW fx_bars AS SELECT * FROM read_parquet('{bars_glob}', hive_partitioning=true, union_by_name=true)"
        )

    def close(self) -> None:
        self.connection.close()
