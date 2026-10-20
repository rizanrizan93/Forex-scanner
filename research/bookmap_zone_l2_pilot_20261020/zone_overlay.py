"""Research-only L2 annotations for pre-existing reversal zones.

Accepts generic zone records, including V225 SD zone exports. Never moves zone
boundaries or emits entry/close orders. It does not claim a calibrated win rate.
"""
from dataclasses import dataclass
from book_adapter import decision_features

@dataclass(frozen=True)
class Zone:
    zone_id: str
    instrument: str
    venue: str
    available_ms: int
    side: int
    low: float
    high: float

def annotate(zone, decision_ms, book_instrument, book_venue, ts_ms, imbalance):
    if zone.instrument != book_instrument or zone.venue != book_venue:
        return {'zone_id':zone.zone_id,'status':'INSTRUMENT_OR_VENUE_MISMATCH','execution_influence':False}
    if zone.available_ms > decision_ms or zone.low > zone.high or zone.side not in (-1,1):
        return {'zone_id':zone.zone_id,'status':'INVALID_OR_FUTURE_ZONE','execution_influence':False}
    f=decision_features(ts_ms,imbalance,decision_ms,zone.side)
    return {'zone_id':zone.zone_id,'zone_low':zone.low,'zone_high':zone.high,
            'status':'RESEARCH_ANNOTATION' if f['feature_valid'] else 'INSUFFICIENT_ORDERBOOK_DATA',
            'execution_influence':False,'calibrated_reversal_probability':None,**f}
