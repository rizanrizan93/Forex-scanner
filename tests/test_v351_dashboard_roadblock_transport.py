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
        "execution_authority": True,
        "execution_scope": "DEMO_ONLY",
        "live_execution_enabled": False,
    })
    row = SupabaseDashboardReader(query).latest_xau_sd_liquidity_operational_heartbeat()
    ev = row["details"]["evaluation"]
    assert ev["nearest_roadblock"]["status"] == "BLOCKS_ENTRY_ROOM"
    assert ev["roadblock_room"]["state"] == "ROADBLOCK_ROOM_TOO_SMALL"
    assert ev["execution_authority"] is True
    assert ev["execution_scope"] == "DEMO_ONLY"
    assert ev["live_execution_enabled"] is False
    assert "nearest_roadblock:details->evaluation->nearest_roadblock" in query.selected
    assert "roadblock_room:details->evaluation->roadblock_room" in query.selected
    assert "execution_authority:details->evaluation->execution_authority" in query.selected
    assert "execution_scope:details->evaluation->>execution_scope" in query.selected


def test_turso_projection_preserves_both_sides_for_v405_and_v406():
    from fx_scanner.xau_whalezone_reconstruction_v405 import evaluate_whalezone_reconstruction_v405
    from fx_scanner.xau_zone_hierarchy_v406 import evaluate_zone_hierarchy_v406
    zones = [
        {'direction': 'LONG', 'timeframe': 'H1', 'low': 4180.0, 'high': 4185.0, 'atr': 10.0, 'score': 80, 'condition': 'FRESH'},
        {'direction': 'SHORT', 'timeframe': 'H1', 'low': 4200.0, 'high': 4205.0, 'atr': 10.0, 'score': 80, 'condition': 'FRESH'},
    ]
    query = _Query({'worker_name': 'ctrader_demo_xau_sd_liquidity_v342', 'price_now': 4192.0,
        'main_reversal_zone': zones[0], 'active_zones': zones,
        'support_resistance_map': {'nearest_support': {'price': 4185.0}},
        'liquidity_candidates': [{'side': 'BUY_SIDE', 'price': 4205.0}]})
    ev = SupabaseDashboardReader(query).latest_xau_sd_liquidity_operational_heartbeat()['details']['evaluation']
    tiered = evaluate_whalezone_reconstruction_v405(ev)
    hierarchy = evaluate_zone_hierarchy_v406(ev)
    assert tiered['buy_zones'] and tiered['sell_zones']
    assert hierarchy['main_buy'] and hierarchy['main_sell']
    assert ev['support_resistance_map']['nearest_support']['price'] == 4185
    assert ev['liquidity_candidates'][0]['price'] == 4205


def test_frozen_core_survives_compact_projection_and_public_sanitization():
    from fx_scanner.xau_dashboard_bridge_v254 import _sanitize
    from fx_scanner.xau_frozen_dd50 import POLICY_HASH, STRATEGY_ID
    core={'strategy_id':STRATEGY_ID,'policy_hash':POLICY_HASH,'state':'WAIT',
        'reason':'OUTSIDE_FROZEN_ENTRY_SESSION','candidate':None,'execution_scope':'DEMO_ONLY'}
    query=_Query({'worker_name':'ctrader_demo_xau_sd_liquidity_v342',
        'observed_at':'2026-10-09T15:00:00+00:00','healthy':True,'git_sha':'new-main-sha',
        'frozen_core':core})
    row=_sanitize(SupabaseDashboardReader(query).latest_xau_sd_liquidity_operational_heartbeat())
    assert row['details']['evaluation']['frozen_core']==core
    assert row['details']['git_sha']=='new-main-sha'
    assert 'frozen_core:details->evaluation->frozen_core' in query.selected
    assert 'details' not in query.selected.split(',')
