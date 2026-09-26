from fx_scanner.demo_xau_structural_targets_v229 import (
    CONTRACT,
    build_structural_target_plan,
)


def _zone(zone_id, timeframe, direction, low, high):
    return {
        "zone_id": zone_id,
        "timeframe": timeframe,
        "direction": direction,
        "low": low,
        "high": high,
        "status": "ACTIVE",
        "lifecycle": {"active": True},
    }


def test_v229_long_targets_follow_m15_h1_h4_and_front_run_supply():
    plan = build_structural_target_plan(
        direction="LONG",
        entry=4258.0,
        stop=4250.0,
        minimum_rr=1.5,
        m15_zones=[
            _zone("m15-s", "M15", "SHORT", 4274.0, 4278.0),
        ],
        htf_zones=[
            _zone("h1-s", "H1", "SHORT", 4290.0, 4300.0),
            _zone("h4-s", "H4", "SHORT", 4320.0, 4340.0),
            _zone("d1-s", "D1", "SHORT", 4380.0, 4420.0),
        ],
    )
    assert plan["contract"] == CONTRACT
    mapped = plan["mapped_targets"]
    assert [row["timeframe"] for row in mapped] == ["M15", "H1", "H4", "D1"]
    assert mapped[0]["target_price"] == 4273.6
    assert mapped[1]["target_price"] == 4289.0
    assert mapped[2]["target_price"] == 4319.0
    assert [row["timeframe"] for row in plan["broker_scaleout_targets"]] == [
        "M15", "H1", "H4"
    ]
    assert plan["macro_terminal_target"]["timeframe"] == "D1"
    assert plan["execution_authority"] is False


def test_v229_short_targets_mirror_to_demand():
    plan = build_structural_target_plan(
        direction="SHORT",
        entry=4350.0,
        stop=4360.0,
        minimum_rr=1.5,
        m15_zones=[
            _zone("m15-d", "M15", "LONG", 4328.0, 4332.0),
        ],
        htf_zones=[
            _zone("h1-d", "H1", "LONG", 4300.0, 4310.0),
            _zone("h4-d", "H4", "LONG", 4260.0, 4280.0),
        ],
    )
    broker = plan["broker_scaleout_targets"]
    assert [row["timeframe"] for row in broker] == ["M15", "H1", "H4"]
    assert broker[0]["target_price"] == 4332.4
    assert broker[1]["target_price"] == 4311.0
    assert broker[2]["target_price"] == 4281.0
    assert all(row["target_price"] < 4350.0 for row in broker)


def test_v229_rr_is_validation_not_target_generator():
    plan = build_structural_target_plan(
        direction="LONG",
        entry=100.0,
        stop=90.0,
        minimum_rr=1.5,
        m15_zones=[
            _zone("near-m15", "M15", "SHORT", 108.0, 110.0),
        ],
        htf_zones=[
            _zone("far-h1", "H1", "SHORT", 120.0, 124.0),
        ],
    )
    mapped = {row["timeframe"]: row for row in plan["mapped_targets"]}
    assert mapped["M15"]["rr_eligible"] is False
    assert mapped["M15"]["target_price"] == 107.8
    assert mapped["H1"]["rr_eligible"] is True
    assert [row["timeframe"] for row in plan["broker_scaleout_targets"]] == ["H1"]


def test_v229_ignores_same_direction_broken_and_behind_zones():
    plan = build_structural_target_plan(
        direction="LONG",
        entry=100.0,
        stop=90.0,
        minimum_rr=1.5,
        m15_zones=[
            _zone("same", "M15", "LONG", 120.0, 122.0),
            _zone("behind", "M15", "SHORT", 95.0, 99.0),
            {
                **_zone("broken", "M15", "SHORT", 120.0, 122.0),
                "status": "BROKEN_RESEARCH_ONLY",
            },
        ],
        htf_zones=[],
    )
    assert plan["mapped_targets"] == []
    assert plan["structural_target_available"] is False
