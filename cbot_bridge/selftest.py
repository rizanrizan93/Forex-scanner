#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path

from server import CONTRACTS, Store, _validate_identity, strict_load


def state(prefix: str, account: int, symbol: str, revision: int) -> dict:
    row = {
        "Schema": CONTRACTS[prefix]["schema"],
        "ContractHash": CONTRACTS[prefix]["hash"],
        "AccountNumber": account,
        "Symbol": symbol,
        "Revision": revision,
    }
    if CONTRACTS[prefix]["execution_model"]:
        row.update(
            ExecutionModel=CONTRACTS[prefix]["execution_model"],
            PendingChildren=0,
            PendingFirstFill=False,
        )
    return row


def main() -> int:
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "state.sqlite")
        cases = [
            ("RZXA1", 1234480, "XAUUSD", "a" * 32),
            ("RZEU4B", 1237903, "EURUSD", "b" * 32),
        ]
        for prefix, account, symbol, lease in cases:
            key = f"{prefix}:{account}:{symbol}"
            _validate_identity(key, lease, CONTRACTS[prefix]["hash"])
            assert store.acquire(key, lease) == (0, None)
            s1 = state(prefix, account, symbol, 1)
            assert store.save(key, lease, 0, 1, s1) == 1
            try:
                store.save(key, lease, 0, 2, state(prefix, account, symbol, 2))
            except ValueError as exc:
                assert str(exc) == "REVISION_CONFLICT"
            else:
                raise AssertionError("revision conflict not rejected")
        try:
            strict_load('{"x":NaN}')
        except ValueError:
            pass
        else:
            raise AssertionError("non-finite JSON accepted")
        store.db.close()
    print("CBOT_BRIDGE_SELFTEST_OK schemas=RZXA1:1,RZEU4B:2 cas=PASS nonfinite=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
