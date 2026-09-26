from datetime import UTC, datetime, timedelta

from fx_scanner.research_xau_causal_mtf_health_router_v235 import route_causally


def _row(i: int, *, pnl_r: float, direction: str = "LONG") -> dict:
    fill = datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=i)
    risk = 10.0
    # Health friction is 0.5 points, so gross_points below maps exactly to pnl_r.
    gross = pnl_r * risk + 0.5
    return {
        "variant_id": "V234_H1SD_M5_H1_TERMINAL",
        "direction": direction,
        "slot": "NEAR_EDGE",
        "fill_at": fill.isoformat(),
        "exit_at": (fill + timedelta(hours=1)).isoformat(),
        "risk_points": risk,
        "gross_points": gross,
        "year": fill.year,
        "trade_key": f"raw-{i}-{direction}",
        "margin_usd_1_to_100": 20.0,
    }


def test_v235_requires_completed_prior_sample_before_routing() -> None:
    rows = [_row(i, pnl_r=0.5) for i in range(35)]
    routed, diagnostics = route_causally(rows)
    # First 30 cannot route because the minimum completed-history sample does not yet exist.
    assert diagnostics["candidate_checks"] == 35
    assert all(int(row["health_at_entry"]["completed_trades"]) >= 30 for row in routed)
    assert len(routed) > 0


def test_v235_suppressed_trades_still_update_shadow_history() -> None:
    rows = []
    # Negative history keeps the router off.
    for i in range(35):
        rows.append(_row(i, pnl_r=-1.0))
    # Later winning candidates are still observed even while suppressed; eventually
    # the trailing 126-day health stream can recover without survivorship bias.
    for i in range(35, 80):
        rows.append(_row(i, pnl_r=2.0))
    routed, diagnostics = route_causally(rows)
    assert diagnostics["candidate_checks"] == 80
    assert len(routed) > 0
    assert routed[0]["fill_at"] > rows[35]["fill_at"]


def test_v235_health_streams_are_direction_specific() -> None:
    rows = [_row(i, pnl_r=0.5, direction="LONG") for i in range(35)]
    rows += [_row(i, pnl_r=-1.0, direction="SHORT") for i in range(35)]
    routed, diagnostics = route_causally(rows)
    assert any(row["direction"] == "LONG" for row in routed)
    assert not any(row["direction"] == "SHORT" for row in routed)
    assert len(diagnostics["streams"]) == 2
