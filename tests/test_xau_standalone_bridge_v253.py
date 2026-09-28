import json
from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest

from fx_scanner.xau_standalone_bridge_v253 import validate_snapshot, fetch_snapshot


def _payload(as_of: datetime) -> dict:
    return {
        "contract": "XAU_RIZAN_STANDALONE_V253",
        "as_of": as_of.isoformat(),
        "safety": {
            "manual_analysis_only": True,
            "execution_authority": False,
        },
        "quote": {"mid": 4260.0},
    }


def test_bridge_marks_recent_snapshot_fresh():
    now = datetime(2026, 9, 28, 1, 0, tzinfo=UTC)
    out = validate_snapshot(_payload(now - timedelta(seconds=40)), now=now)
    assert out["bridge"]["fresh"] is True
    assert out["bridge"]["age_seconds"] == 40.0


def test_bridge_marks_old_snapshot_stale():
    now = datetime(2026, 9, 28, 1, 0, tzinfo=UTC)
    out = validate_snapshot(_payload(now - timedelta(seconds=240)), now=now)
    assert out["bridge"]["fresh"] is False


def test_bridge_rejects_execution_authority():
    now = datetime(2026, 9, 28, 1, 0, tzinfo=UTC)
    payload = _payload(now)
    payload["safety"]["execution_authority"] = True
    with pytest.raises(ValueError, match="execution authority"):
        validate_snapshot(payload, now=now)


def test_fetch_bridge_accepts_json_without_ctrader_dependency():
    now = datetime(2026, 9, 28, 1, 0, tzinfo=UTC)
    body = json.dumps(_payload(now)).encode()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return body

    seen = {}

    def opener(request, timeout):
        assert timeout == 8.0
        seen["url"] = request.full_url
        return Response()

    out = fetch_snapshot("https://example.invalid/snapshot.json", now=now, opener=opener)
    assert out["bridge"]["fresh"] is True
    assert "_rizan=" in seen["url"]
