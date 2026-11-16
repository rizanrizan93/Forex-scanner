import hashlib
import math
import struct
from datetime import datetime,timezone,timedelta
from unittest.mock import patch

import pytest
from fx_scanner import btc_native_readonly as btc
from fx_scanner.frozen_v1_directional_score import _family,evaluate_bias

@pytest.fixture(scope='module')
def seed():
    rows=[]
    for i in range(68280):
        at=1546300800 if i==0 else btc.SEED_END-(68280-i)*3600
        c=100+math.sin(i/40)*5
        rows.append([at,c-.1,c+1,c-1,c,60])
    digest=hashlib.sha256()
    for row in rows:digest.update(struct.pack('<qddddi',*row))
    return rows,digest.hexdigest()


def make_packet(seed):
    rows,sha=seed
    return dict(contract=btc.CONTRACT,source=btc.SOURCE,through=btc.SEED_END,
                seed_hash=sha,bars=rows,read_only=True,execution_authority=False)


def test_seed_hash_and_metadata_are_enforced(seed):
    rows,sha=seed
    p=make_packet(seed)
    with patch.object(btc,'SEED_HASH',sha):
        assert len(btc.validate_seed(p))==68280
        damaged=dict(p,bars=[list(r) for r in rows]);damaged['bars'][12][4]+=.01
        with pytest.raises(ValueError,match='HASH'):btc.validate_seed(damaged)
        with pytest.raises(ValueError,match='CONTRACT'):btc.validate_seed(dict(p,source='BROKER_CFD'))


def test_native_mirror_scores_both_sides_without_broker_market_and_never_claims_order(seed):
    p=make_packet(seed);now=datetime.fromtimestamp(btc.SEED_END,timezone.utc)+timedelta(minutes=10)
    with patch.object(btc,'SEED_HASH',seed[1]):
        item=evaluate_bias(None,phase='GROWTH',now=now,btc_native=p)['symbols']['BTCUSD']
    assert item['BUY']['score'] is not None and item['SELL']['score'] is not None
    assert item['BUY']['coverage']==100
    assert item['native_source']['seed_verified'] is True
    assert item['native_source']['terminal_acceptance']=='UNKNOWN'
    assert item['native_order_signal']=='NOT_EVALUATED'
    assert item['execution_authority'] is False


def test_stale_native_packet_wrong_source_and_writing_authority_are_rejected(seed):
    p=make_packet(seed);now=datetime.fromtimestamp(btc.SEED_END,timezone.utc)
    with patch.object(btc,'SEED_HASH',seed[1]):
        for change in [dict(through=btc.SEED_END-3600),dict(source='BROKER_CFD'),dict(execution_authority=True),dict(read_only=False)]:
            with pytest.raises(ValueError):btc.score_packet(dict(p,**change),now,_family)
        with pytest.raises(ValueError):btc.score_packet(p,now+timedelta(hours=1),_family)


def test_extension_gap_never_backfilled_or_synthesized(seed):
    rows,sha=seed
    with patch.object(btc,'SEED_HASH',sha):
        with pytest.raises(ValueError,match='GAP'):
            btc.build_packet(btc.SEED_END+3600,rows,lambda start,end:[])
        packet=btc.build_packet(btc.SEED_END+3600,rows,lambda start,end:[[t,100.,102.,99.,101.,1] for t in range(start,end,60)])
        assert packet['bars'][-1]==[btc.SEED_END,100.,102.,99.,101.,60]
        packet['bars'][-1][5]=59
        with pytest.raises(ValueError,match='GAP'):
            btc.score_packet(packet,datetime.fromtimestamp(btc.SEED_END+3600,timezone.utc),_family)


def test_native_feature_initialization_matches_frozen_csharp_not_sma():
    rows=[[0,100,110,90,105,60],[3600,105,120,100,115,60]]
    f=btc.features(rows)
    assert f[0]['atr']==20 and f[0]['e20']==105 and f[0]['rsi']==100
    assert f[1]['e20']==105+2/21*10
    assert f[1]['e80']==105+2/81*10


def test_unknown_phase_and_seed_phase_never_activate_btc(seed):
    now=datetime.fromtimestamp(btc.SEED_END,timezone.utc)
    with patch.object(btc,'SEED_HASH',seed[1]):
        for phase in ['UNKNOWN','SEED']:
            item=evaluate_bias(None,phase=phase,now=now,btc_native=make_packet(seed))['symbols']['BTCUSD']
            assert item['BUY']['score'] is None and item['SELL']['score'] is None


def test_partial_h4_never_included_in_native_features(seed):
    rows,sha=seed
    with patch.object(btc,'SEED_HASH',sha):
        p=btc.build_packet(btc.SEED_END+3600,rows,lambda a,b:[[t,100.,102.,99.,101.,1] for t in range(a,b,60)])
        _,meta=btc.score_packet(p,datetime.fromtimestamp(p['through'],timezone.utc),_family)
        assert meta['h4_close']==datetime.fromtimestamp(btc.SEED_END,timezone.utc).isoformat()


def test_bitstamp_response_order_and_boundary_extras_match_native_handling():
    import json
    start=btc.SEED_END
    def row(at,close='101'):
        return dict(timestamp=str(at),open='100',high='102',low='99',close=close)
    response=dict(data=dict(ohlc=[row(start+60),row(start),row(start+120)]))
    with patch.object(btc,'get_bytes',return_value=json.dumps(response).encode()):
        assert [r[0] for r in btc.load_minutes(start,start+120)]==[start,start+60]
    response['data']['ohlc'].append(row(start,'100.5'))
    with patch.object(btc,'get_bytes',return_value=json.dumps(response).encode()):
        with pytest.raises(ValueError,match='CONFLICT'):btc.load_minutes(start,start+120)


def test_bitstamp_missing_minute_stays_missing():
    import json
    start=btc.SEED_END
    response=dict(data=dict(ohlc=[dict(timestamp=str(start),open='100',high='102',low='99',close='101')]))
    with patch.object(btc,'get_bytes',return_value=json.dumps(response).encode()):
        with pytest.raises(ValueError,match='GAP'):btc.load_minutes(start,start+120)
