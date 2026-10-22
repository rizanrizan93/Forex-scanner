"""Contract tests for the read-only predictive A->B projection."""
from datetime import datetime, timedelta, timezone

from fx_scanner.predictive_zone_to_zone import build_zone_paths

NOW = datetime(2026, 10, 22, 7, 0, tzinfo=timezone.utc)


def stamp(t):
    return t.isoformat()


def zone(side, ident, low, high):
    return dict(id=ident, side=side, timeframe="H1",
                low=low, high=high, family=0,
                state="WATCH_ZONE_ONLY", formed_at=stamp(NOW - timedelta(hours=1)))


def watch():
    sell = zone("SELL", "sell-a", 4100, 4102)
    buy = zone("BUY", "buy-b", 4070, 4072)
    checks = {
        z["id"]: dict(first_touch_at=None, observed_touch_at=None,
                      observation_status="MENUNGGU_SENTUHAN",
                      m1_audit=dict(unverified_minutes=0, m1_bars=60),
                      sl=(4103 if z["side"] == "SELL" else 4069))
        for z in (sell, buy)
    }
    ns = int((NOW - timedelta(hours=1)).timestamp() * 1e9)
    nodes = [dict(tf=60, direction=(-1 if z["side"] == "SELL" else 1),
                  formed_ns=ns, low=z["low"], high=z["high"], atr=5)
             for z in (sell, buy)]
    return dict(contract="RIZAN_ZONE_V05_DASHBOARD_1",
                execution_authority=False, execution_influence=False,
                as_of=stamp(NOW), evaluated_close_at=stamp(NOW),
                price_reference=4092, ema_bias=dict(H1="SELL", H4="SELL"),
                watch_zones=[sell, buy], watch_checks=checks,
                node_registry=nodes, supply_demand_zones=[], plans=[])


def test_limit_zone_to_zone_before_first_touch():
    p = build_zone_paths(watch(), now=NOW + timedelta(seconds=15))
    sell = next(z for z in p["limit"] if z["side"] == "SELL")
    assert sell["state"] == "WATCH"
    assert sell["source"]["id"] == "sell-a"
    assert sell["target"]["id"] == "buy-b"
    assert sell["entry_reference"] == 4100
    assert sell["sl_reference"] == 4103
    assert abs(sell["tp_reference"] - 4072.25) < 0.001
    assert sell["gross_rr"] > 1.5
    assert not sell["entry_allowed"]
    assert p["calibrated_probability"] is None
    assert p["execution_authority"] is False


def test_no_opposing_zone_does_not_invent_tp():
    x = watch()
    x["watch_zones"] = [z for z in x["watch_zones"] if z["side"] == "SELL"]
    p = build_zone_paths(x, now=NOW)
    assert p["limit"][0]["state"] == "WAIT"
    assert p["limit"][0]["reason"] == "ZONA_B_LAWAN_BELUM_TERVALIDASI"
    assert p["limit"][0]["tp_reference"] is None


def test_unverified_history_blocks_limit_and_target():
    x = watch()
    x["watch_checks"]["sell-a"]["m1_audit"]["unverified_minutes"] = 1
    p = build_zone_paths(x, now=NOW)
    sell = next(z for z in p["limit"] if z["side"] == "SELL")
    assert sell["state"] == "WAIT"
    assert sell["reason"] == "FIRST_TOUCH_BELUM_TERBUKTI_FRESH"


def test_stale_feed_hides_all_levels():
    p = build_zone_paths(watch(), now=NOW + timedelta(minutes=8))
    assert p["state"] == "WAIT"
    assert p["price"] is None and p["limit"] == []
    assert p["confirmed"] == []


def test_invalid_and_pending_zones_never_get_limit_watch():
    x = watch()
    x["watch_zones"][0]["state"] = "PENDING_INVALIDATION"
    p = build_zone_paths(x, now=NOW)
    sell = next(z for z in p["limit"] if z["side"] == "SELL")
    assert sell["state"] == "WAIT"
    assert sell["reason"] == "PENDING_INVALIDATION_ATAU_DATA_ZONA"


def test_confirmed_is_only_existing_v05_reference():
    x = watch()
    x["plans"] = [dict(
        source=zone("SELL", "confirmed-a", 4100, 4102),
        state="ENTRY", reason="SYARAT_M15_M5_TERPENUHI",
        first_touch_at=stamp(NOW - timedelta(minutes=20)),
        reclaim_m15_at=stamp(NOW - timedelta(minutes=10)),
        confirmation_m5_at=stamp(NOW - timedelta(minutes=5)),
        entry=4099, sl=4103, tp=4078,
        target=zone("BUY", "target-c", 4070, 4072),
        planned_net_rr=4.0)]
    p = build_zone_paths(x, now=NOW)
    assert p["confirmed"][0]["state"] == "ENTRY_REFERENSI"
    assert p["confirmed"][0]["entry_allowed"] is False
    x["plans"][0]["confirmation_m5_at"] = None
    assert build_zone_paths(x, now=NOW)["confirmed"][0]["state"] == "WAIT"
