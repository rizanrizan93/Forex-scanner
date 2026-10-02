from types import SimpleNamespace

from fx_scanner.dashboard import SupabaseDashboardReader
from fx_scanner.xau_dashboard_bridge_v254 import HOT_HEARTBEATS


class _Query:
    def __init__(self, rows_by_worker):
        self.rows_by_worker = rows_by_worker
        self.worker = None
        self.selected = None

    def table(self, name):
        assert name == "runtime_heartbeats"
        return self

    def select(self, fields):
        self.selected = fields
        return self

    def eq(self, field, value):
        assert field == "worker_name"
        self.worker = value
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, n):
        assert n == 1
        return self

    def execute(self):
        row = self.rows_by_worker.get(self.worker)
        return SimpleNamespace(data=[] if row is None else [row])


def test_v359_event_projection_preserves_forecast_previous_and_components():
    query = _Query({
        "ctrader_demo_xau_event_risk_v192": {
            "worker_name": "ctrader_demo_xau_event_risk_v192",
            "observed_at": "2026-10-02T12:24:41+00:00",
            "healthy": True,
            "lag_seconds": 0,
            "dashboard": {
                "state": "PRE_EVENT",
                "action": "PREPARE_ONLY_AVOID_NEW_CHASE",
                "focal_event": {
                    "title": "Employment Situation",
                    "forecast": 89000,
                    "previous": 162000,
                    "gold_bias": "GOLD_BULLISH",
                },
                "upcoming_events": [
                    {"title": "Employment Situation", "forecast": 89000, "previous": 162000},
                    {"title": "Unemployment Rate", "forecast": 4.1, "previous": 4.1},
                    {"title": "Average Hourly Earnings m/m", "forecast": 0.3, "previous": 0.3},
                ],
                "minutes_to_focal": 5.0,
                "execution_authority": False,
                "execution_influence": False,
            },
        }
    })
    row = SupabaseDashboardReader(query).latest_xau_event_risk_operational_heartbeat()
    risk = row["details"]["risk"]
    assert risk["focal_event"]["forecast"] == 89000
    assert risk["focal_event"]["previous"] == 162000
    assert [x["title"] for x in risk["upcoming_events"][:3]] == [
        "Employment Situation",
        "Unemployment Rate",
        "Average Hourly Earnings m/m",
    ]
    assert row["details"]["transport_projection"] == "V192_EVENT_OPERATIONAL_60S"
    assert "dashboard:details->dashboard_projection" in query.selected


def test_v359_macro_projection_keeps_broader_bias_and_components():
    query = _Query({
        "ctrader_demo_xau_macro_attribution_v357": {
            "worker_name": "ctrader_demo_xau_macro_attribution_v357",
            "observed_at": "2026-10-02T12:24:44+00:00",
            "healthy": True,
            "lag_seconds": 0,
            "dashboard": {
                "state": "BROAD_MACRO_MIXED",
                "broader_macro_bias": "NEUTRAL_MIXED",
                "macro_score": 0.5,
                "confidence": "LOW",
                "coverage": 0.75,
                "components": {"US10Y": {"delta": 3.0, "freshness": "FRESH"}},
                "event_consensus_bias": "BULLISH_XAU",
                "consensus_relationship": "NO_CLEAR_DIRECTIONAL_COMPARISON",
                "fed_repricing_proxy": {"state": "NEUTRAL_REPRICING_PROXY"},
                "execution_authority": False,
                "execution_influence": False,
            },
        }
    })
    row = SupabaseDashboardReader(query).latest_xau_macro_attribution_operational_heartbeat()
    ev = row["details"]["evaluation"]
    assert ev["broader_macro_bias"] == "NEUTRAL_MIXED"
    assert ev["coverage"] == 0.75
    assert ev["components"]["US10Y"]["delta"] == 3.0
    assert ev["event_consensus_bias"] == "BULLISH_XAU"
    assert row["details"]["transport_projection"] == "V357_MACRO_OPERATIONAL_60S"


def test_v359_bridge_does_not_depend_on_generic_full_v192_read():
    assert "ctrader_demo_xau_event_risk_v192" not in HOT_HEARTBEATS

    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    bridge = (root / "src/fx_scanner/xau_dashboard_bridge_v254.py").read_text()
    streamlit = (root / "streamlit_app.py").read_text()
    assert "latest_xau_event_risk_operational_heartbeat()" in bridge
    assert "latest_xau_macro_attribution_operational_heartbeat()" in bridge
    assert "latest_xau_event_risk_operational_heartbeat()" in streamlit
    assert "latest_xau_macro_attribution_operational_heartbeat()" in streamlit



def test_v360_source_projection_prunes_internal_event_metadata_but_keeps_display_data():
    from fx_scanner.demo_xau_event_risk_v192 import build_dashboard_projection

    projection = build_dashboard_projection({
        "state": "PRE_EVENT",
        "action": "PREPARE_ONLY_AVOID_NEW_CHASE",
        "focal_event": {
            "title": "Employment Situation",
            "forecast": 89000,
            "previous": 162000,
            "gold_bias": "GOLD_BULLISH",
            "scheduled_at_wib": "2026-10-02T19:30:00+07:00",
            "event_id": "large-internal-id",
            "source_url": "https://example.invalid/very/long/internal/url",
        },
        "upcoming_events": [{
            "title": "Unemployment Rate",
            "forecast": 4.1,
            "previous": 4.1,
            "scheduled_at_wib": "2026-10-02T19:30:00+07:00",
            "event_id": "internal",
            "source_url": "https://example.invalid/metadata",
        }],
        "minutes_to_focal": 3.0,
    })
    focal = projection["focal_event"]
    assert focal["forecast"] == 89000
    assert focal["previous"] == 162000
    assert "event_id" not in focal
    assert "source_url" not in focal
    assert projection["upcoming_events"][0]["title"] == "Unemployment Rate"


def test_v360_macro_source_projection_keeps_only_dashboard_component_fields():
    from fx_scanner.demo_xau_macro_attribution_v357 import build_dashboard_projection

    projection = build_dashboard_projection({
        "state": "BROAD_MACRO_MIXED",
        "broader_macro_bias": "NEUTRAL_MIXED",
        "macro_score": 0.5,
        "confidence": "LOW",
        "coverage": 0.75,
        "components": {
            "US10Y": {
                "delta": 3.0,
                "freshness": "FRESH",
                "provider": "FEDERAL_RESERVE_FRED",
                "source_url": "https://example.invalid/long",
                "observed_at": "2026-09-30T00:00:00+00:00",
            }
        },
        "event_consensus_bias": "BULLISH_XAU",
        "consensus_relationship": "NO_CLEAR_DIRECTIONAL_COMPARISON",
        "fed_repricing_proxy": {
            "state": "NEUTRAL_REPRICING_PROXY",
            "delta_bps": -1.0,
            "source": "verbose internal description",
        },
    })
    row = projection["components"]["US10Y"]
    assert row["delta"] == 3.0
    assert row["freshness"] == "FRESH"
    assert "source_url" not in row
    assert "observed_at" not in row
    assert projection["fed_repricing_proxy"] == {
        "state": "NEUTRAL_REPRICING_PROXY",
        "delta_bps": -1.0,
    }
