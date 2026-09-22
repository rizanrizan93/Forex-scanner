from datetime import datetime,timedelta,timezone

from fx_scanner.models import Bar
from fx_scanner.demo_xau_afic_path_shadow_observer import (
    FORWARD_CONTRACT,STRATEGY_ID,SYMBOL,OriginZone,_resample_completed,
    _choose_zone,_zone_diagnostics
)

UTC=timezone.utc

def _bar(ts,px):
    return Bar("XAUUSD","M15",ts,px,px+1,px-1,px+0.2,1,0.1,0.2)

def test_afic_shadow_identity():
    assert SYMBOL=="XAUUSD"
    assert STRATEGY_ID=="XAU_AFIC_PATH_SHADOW_V1"
    assert FORWARD_CONTRACT=="XAU_AFIC_PATH_SHADOW_FORWARD_V1"

def test_afic_live_resample_excludes_forming_h4():
    start=datetime(2026,9,21,0,0,tzinfo=UTC)
    rows=tuple(_bar(start+timedelta(minutes=15*i),4300+i) for i in range(20))
    # At 04:45 UTC the 04:00-08:00 H4 bucket is still forming. Only the
    # completed 00:00-04:00 H4 bar may be used by the AFIC map.
    frame=_resample_completed(rows,"4h",as_of=datetime(2026,9,21,4,45,tzinfo=UTC))
    assert len(frame)==1
    assert frame.iloc[-1]["time"].to_pydatetime()==datetime(2026,9,21,4,0,tzinfo=UTC)


def _zone(direction,available_at,low,high):
    return OriginZone(
        direction=direction,
        available_at=available_at,
        bos_at=available_at,
        bos_level=low if direction=="SHORT" else high,
        low=low,
        high=high,
        h1_atr=10.0,
        origin_at=available_at-timedelta(hours=1),
        displacement_range_atr=1.2,
        displacement_body_fraction=0.65,
    )


def test_zone_diagnostics_explains_no_short_map_zone_without_bug():
    map_at=datetime(2026,9,22,4,0,tzinfo=UTC)
    zones=(
        _zone("SHORT",map_at-timedelta(hours=2),4320.0,4330.0),
        _zone("SHORT",map_at-timedelta(hours=30),4380.0,4390.0),
        _zone("LONG",map_at-timedelta(hours=3),4310.0,4318.0),
    )
    x=_zone_diagnostics(
        zones,map_at=map_at,price=4340.0,continuation="SHORT"
    )
    assert x["origin_zones_total"]==3
    assert x["fresh_within_24h"]==2
    assert x["matching_direction_fresh"]==1
    assert x["wrong_side_of_anchor"]==1
    assert x["eligible_correct_side"]==0
    assert x["selection_result"]=="NO_ELIGIBLE_MAP_ZONE"


def test_zone_diagnostics_identifies_nearest_eligible_short_zone():
    map_at=datetime(2026,9,22,4,0,tzinfo=UTC)
    zones=(
        _zone("SHORT",map_at-timedelta(hours=2),4350.0,4360.0),
        _zone("SHORT",map_at-timedelta(hours=1),4370.0,4380.0),
    )
    x=_zone_diagnostics(
        zones,map_at=map_at,price=4340.0,continuation="SHORT"
    )
    assert x["eligible_correct_side"]==2
    assert x["selection_result"]=="ELIGIBLE_ZONE_FOUND"
    assert x["nearest_eligible"]["low"]==4350.0
    assert x["nearest_eligible"]["distance_points"]==10.0


def test_opposite_long_zone_becomes_shadow_reversal_watch_on_short_map():
    map_at=datetime(2026,9,22,4,0,tzinfo=UTC)
    long_zone=_zone("LONG",map_at-timedelta(hours=3),4310.0,4320.0)
    bars=(
        Bar("XAUUSD","M15",map_at,4340.0,4342.0,4338.0,4339.0,1,0.1,0.2),
        Bar("XAUUSD","M15",map_at+timedelta(minutes=15),4339.0,4340.0,4334.0,4335.0,1,0.1,0.2),
    )
    x=_zone_diagnostics(
        (long_zone,),
        map_at=map_at,
        price=4341.66,
        continuation="SHORT",
        bars=bars,
    )
    assert x["matching_direction_fresh"]==0
    assert x["opposite_direction_fresh"]==1
    assert x["active_alternative_watch_count"]==1
    watch=x["alternative_reversal_watch_zones"][0]
    assert watch["direction"]=="LONG"
    assert watch["role"]=="DOWNSIDE_DESTINATION_LONG_REVERSAL_WATCH"
    assert watch["status"]=="ACTIVE_WATCH"
    assert watch["auto_execution_authority"] is False
    assert watch["required_confirmation"]=="H1/M15_BULLISH_REVERSAL_REMAP"


def test_reversal_watch_marks_long_zone_invalid_after_close_below_zone():
    map_at=datetime(2026,9,22,4,0,tzinfo=UTC)
    long_zone=_zone("LONG",map_at-timedelta(hours=2),4310.0,4320.0)
    bars=(
        Bar("XAUUSD","M15",map_at,4340.0,4342.0,4315.0,4318.0,1,0.1,0.2),
        Bar("XAUUSD","M15",map_at+timedelta(minutes=15),4318.0,4320.0,4305.0,4308.0,1,0.1,0.2),
    )
    x=_zone_diagnostics(
        (long_zone,),
        map_at=map_at,
        price=4341.66,
        continuation="SHORT",
        bars=bars,
    )
    watch=x["alternative_reversal_watch_zones"][0]
    assert watch["first_touch_at"] is not None
    assert watch["invalidated_at"] is not None
    assert watch["status"]=="INVALIDATED"
    assert x["active_alternative_watch_count"]==0


def test_reversal_watch_preserves_touch_before_current_h4_map():
    map_at=datetime(2026,9,22,8,0,tzinfo=UTC)
    zone=_zone("SHORT",map_at-timedelta(hours=4),4335.0,4343.0)
    bars=(
        Bar("XAUUSD","M15",map_at-timedelta(hours=2),4330.0,4338.0,4329.0,4332.0,1,0.1,0.2),
        Bar("XAUUSD","M15",map_at,4320.0,4325.0,4318.0,4322.0,1,0.1,0.2),
        Bar("XAUUSD","M15",map_at+timedelta(minutes=15),4322.0,4326.0,4320.0,4324.0,1,0.1,0.2),
    )
    x=_zone_diagnostics(
        (zone,),map_at=map_at,price=4322.0,continuation="LONG",bars=bars
    )
    watch=x["alternative_reversal_watch_zones"][0]
    assert watch["first_touch_at"]==(
        map_at-timedelta(hours=2)
    ).isoformat()
    assert watch["map_first_touch_at"] is None
    assert watch["touch_lifecycle"]=="TOUCHED_BEFORE_CURRENT_MAP"
    assert watch["status"]=="ACTIVE_WATCH"


def test_reversal_watch_distinguishes_touch_during_current_h4_map():
    map_at=datetime(2026,9,22,8,0,tzinfo=UTC)
    zone=_zone("SHORT",map_at-timedelta(hours=4),4335.0,4343.0)
    bars=(
        Bar("XAUUSD","M15",map_at-timedelta(hours=2),4320.0,4324.0,4318.0,4322.0,1,0.1,0.2),
        Bar("XAUUSD","M15",map_at,4330.0,4338.0,4329.0,4332.0,1,0.1,0.2),
    )
    x=_zone_diagnostics(
        (zone,),map_at=map_at,price=4322.0,continuation="LONG",bars=bars
    )
    watch=x["alternative_reversal_watch_zones"][0]
    assert watch["first_touch_at"]==map_at.isoformat()
    assert watch["map_first_touch_at"]==map_at.isoformat()
    assert watch["touch_lifecycle"]=="TOUCHED_DURING_CURRENT_MAP"
    assert watch["status"]=="TOUCHED_WATCH_REVERSAL"


def test_zone_identity_is_stable_across_h4_maps():
    first_map=datetime(2026,9,22,8,0,tzinfo=UTC)
    second_map=first_map+timedelta(hours=4)
    zone=_zone("SHORT",first_map-timedelta(hours=4),4335.0,4343.0)
    bars=(
        Bar("XAUUSD","M15",first_map,4320.0,4324.0,4318.0,4322.0,1,0.1,0.2),
    )
    a=_zone_diagnostics(
        (zone,),map_at=first_map,price=4322.0,continuation="LONG",bars=bars
    )["alternative_reversal_watch_zones"][0]
    b=_zone_diagnostics(
        (zone,),map_at=second_map,price=4322.0,continuation="LONG",bars=bars
    )["alternative_reversal_watch_zones"][0]
    assert a["zone_id"]==b["zone_id"]


def test_zone_invalidated_before_current_map_cannot_revive_as_active_watch():
    map_at=datetime(2026,9,22,8,0,tzinfo=UTC)
    zone=_zone("SHORT",map_at-timedelta(hours=4),4335.0,4343.0)
    invalidated_at=map_at-timedelta(hours=2)
    bars=(
        Bar("XAUUSD","M15",invalidated_at,4338.0,4345.0,4336.0,4344.0,1,0.1,0.2),
        Bar("XAUUSD","M15",map_at,4332.0,4338.0,4330.0,4334.0,1,0.1,0.2),
    )
    x=_zone_diagnostics(
        (zone,),map_at=map_at,price=4322.0,continuation="LONG",bars=bars
    )
    watch=x["alternative_reversal_watch_zones"][0]
    assert watch["invalidated_at"]==invalidated_at.isoformat()
    assert watch["map_first_touch_at"] is None
    assert watch["invalidated_before_map"] is True
    assert watch["zone_lifecycle"]=="INVALIDATED_BEFORE_CURRENT_MAP"
    assert watch["status"]=="INVALIDATED"
    assert x["active_alternative_watch_count"]==0


def test_invalidated_matching_zone_is_not_eligible_on_later_map():
    map_at=datetime(2026,9,22,8,0,tzinfo=UTC)
    zone=_zone("SHORT",map_at-timedelta(hours=4),4335.0,4343.0)
    bars=(
        Bar("XAUUSD","M15",map_at-timedelta(hours=2),4338.0,4345.0,4336.0,4344.0,1,0.1,0.2),
        Bar("XAUUSD","M15",map_at,4322.0,4326.0,4320.0,4324.0,1,0.1,0.2),
    )
    diagnostics=_zone_diagnostics(
        (zone,),map_at=map_at,price=4322.0,continuation="SHORT",bars=bars
    )
    assert diagnostics["invalidated_before_map"]==1
    assert diagnostics["structurally_active_fresh"]==0
    assert diagnostics["eligible_correct_side"]==0
    assert _choose_zone(
        (zone,),map_at=map_at,price=4322.0,continuation="SHORT",bars=bars
    ) is None
