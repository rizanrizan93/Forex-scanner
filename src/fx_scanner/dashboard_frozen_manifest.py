"""Read frozen display metadata without loading any order/execution code."""
from hashlib import sha256
import json
from pathlib import Path

HASHES = {
    "XAUUSD": "48ebaaf55e089e06f9f72573a7e6cc1c10805f85f4b5114e0f3a4e33088d6e16",
    "EURUSD": "0e14ca6e5fe16d3383ca086fc7253aca40b1f65e85c4b70e9e0385a0510c0e63",
}


def manifest(symbol, path=None):
    path = path or Path(__file__).resolve().parents[2]/"config/frozen"/(symbol.lower()+"_layering_1m_v1.json")
    data = json.loads(Path(path).read_text())
    digest = sha256(json.dumps(data["contract"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if digest != HASHES[symbol] or data["policy_hash"] != digest or data["contract"]["symbol"] != symbol:
        raise RuntimeError("LAYERING_FROZEN_HASH_MISMATCH")
    return data
