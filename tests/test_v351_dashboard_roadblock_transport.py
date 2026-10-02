from types import SimpleNamespace

from fx_scanner.dashboard import SupabaseDashboardReader


class _Query:
    def __init__(self, row):
        self.row = row
        self.selected = None

    def table(self, name):
        assert name == "runtime_heartbeats"
        return self

    def select(self, fields):
        self.selected = fields
        return self

    def eq(self, field, value):
        assert field == "worker_name"
        assert value == "ctrader_demo_xau_sd_liquidity_v342"
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, n):
        assert n == 1
        return self

    def execute(self):
        return SimpleNamespace(data=[self.row])


def test_v351_compact_dashboard_keeps_roadblock_fields():
    query = _Query({
        "worker_name": "ctrader_demo_xau_sd_liquidity_v342",
        "observed_at": "2026-10-02T07:20:00+00:00",
        "healthy": True,
        "lag_seconds": 0,
        "state": "MAP_AVAILABLE",
        "price_now": 4192.0,
        "main_reversal_zone": {"timeframe": "H4", "direction": "SHORT"},
        "refinement_zone": {},
        "structural_destination": {"low": 4144.56, "high": 4175.17},
        "structural_room": {"state": "STRUCTURAL_ROOM_OK", "blocked": False},
        "nearest_roadblock": {
            "timeframe": "H1",
            "type": "DEMAND",
            "low": 4180.0,
            "high": 4184.0,
            "status": "BLOCKS_ENTRY_ROOM",
        },
        "roadblock_room": {
            "state": "ROADBLOCK_ROOM_TOO_SMALL",
            "blocked": True,
        },
        "structural_checkpoints": [],
        "failure_path": {},
        "micro_confirmation": {"stage": "WAIT"},
        "entry_guide": {"state": "WAIT_ROADBLOCK"},
        "market_structure": {},
        "expected_reversal_direction": "SHORT",
    })
    row = SupabaseDashboardReader(query).latest_xau_sd_liquidity_operational_heartbeat()
    ev = row["details"]["evaluation"]
    assert ev["nearest_roadblock"]["status"] == "BLOCKS_ENTRY_ROOM"
    assert ev["roadblock_room"]["state"] == "ROADBLOCK_ROOM_TOO_SMALL"
    assert "nearest_roadblock:details->evaluation->nearest_roadblock" in query.selected
    assert "roadblock_room:details->evaluation->roadblock_room" in query.selected
