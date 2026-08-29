from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


class JsonlAuditStore:
    """Small operational audit sink. Not a substitute for Parquet market-data history."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: Any) -> None:
        if is_dataclass(record):
            payload = asdict(record)
        elif isinstance(record, dict):
            payload = dict(record)
        else:
            raise TypeError("record must be dataclass or dict")

        def default(obj: Any):
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise TypeError(f"not JSON serializable: {type(obj)!r}")

        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, default=default, sort_keys=True) + "\n")
