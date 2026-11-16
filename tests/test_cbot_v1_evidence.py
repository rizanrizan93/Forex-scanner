import unittest
from datetime import datetime, timedelta, timezone
from fx_scanner.cbot_v1_evidence import evidence
from fx_scanner.cbot_v1_dashboard import fetch_json, MARKET_URL
from unittest.mock import patch, MagicMock
import json

NOW = datetime(2026, 11, 16, 5, 2, tzinfo=timezone.utc)

def market():
    bars = []
    for i in range(11):
        bars.append(dict(timestamp=(NOW.replace(minute=0)-timedelta(hours=11-i)).isoformat(),
                         open=100, high=104, low=98, close=102, volume=1000))
    return dict(contract='RIZAN_BOOTSTRAP125_MARKET_READONLY_V1', account_suffix='7903',
                read_only=True, execution_authority=False, observed_at=NOW.isoformat(), bars={'XAUUSD': {'H1':bars}})

def broker():
    return dict(contract='RIZAN_BOOTSTRAP125_BROKER_READONLY_V1',account_suffix='7903',read_only=True,
                execution_authority=False,observed_at=NOW.isoformat(),status='OBSERVED',orders_history_checked=True,
                deals_history_checked=True,foreign_exposure_present=True,unmapped_deals=37,
                roles={'XAUUSD':dict(orders=0,deals=0,entry_fills=0,rejected_orders=0)})

def result(m=None,b=None):
    return {k:(v,d) for k,v,d in evidence(m,b,'XAUUSD','GROWTH',NOW)}

class EvidenceTests(unittest.TestCase):
    def test_real_candle_failure_is_distinct_from_missing_native_data(self):
        r=result(market(),broker())
        self.assertFalse(r['Displacement: body ≥ 1,5 × rerata 10 body'][0])
        self.assertFalse(r['Displacement: breakout dan posisi close BUY/SELL'][0])
        self.assertIsNone(r['History/warmup native V1 lengkap'][0])
        self.assertTrue(r['Riwayat order broker berhasil diperiksa'][0])
        self.assertFalse(r['Akun bebas exposure di luar label V1 pada snapshot broker'][0])
        self.assertIn('37',r['Record V1 pada riwayat broker'][1])
        self.assertIsNone(r['Record V1 pada riwayat broker'][0])

    def test_positive_pattern_cannot_certify_native_setup_or_order(self):
        m=market();m['bars']['XAUUSD']['H1'][-1].update(close=110,high=111)
        r=result(m,broker())
        self.assertTrue(r['Displacement: body ≥ 1,5 × rerata 10 body'][0])
        self.assertTrue(r['Displacement: breakout dan posisi close BUY/SELL'][0])
        self.assertIsNone(r['Setup frozen compression/displacement terpenuhi'][0])

    def test_stale_wrong_identity_and_execution_authority_never_count_as_evidence(self):
        for key,value in [('account_suffix','4480'),('execution_authority',True),('observed_at',(NOW-timedelta(minutes=5)).isoformat())]:
            m=market();m[key]=value;b=broker();b[key]=value
            self.assertFalse(any(v is not None for v,d in result(m,b).values() if d.startswith(('11 bar','Observasi'))))
            self.assertIsNone(result(m,b)['Candle broker H1 tertutup dan baru'][0])
            self.assertIsNone(result(m,b)['Riwayat deal broker berhasil diperiksa'][0])

    def test_unclosed_duplicate_or_invalid_ohlc_not_used_for_pattern(self):
        for change in ('future','duplicate','nan','invalid'):
            m=market();bars=m['bars']['XAUUSD']['H1']
            if change=='future':bars[-1]['timestamp']=NOW.isoformat()
            if change=='duplicate':bars[-1]['timestamp']=bars[-2]['timestamp']
            if change=='nan':bars[-1]['close']=float('nan')
            if change=='invalid':bars[-1]['low']=999
            r=result(m)
            self.assertFalse(r['Candle broker H1 tertutup dan baru'][0])
            self.assertNotIn('Displacement: body ≥ 1,5 × rerata 10 body',r)

    def test_btc_cfd_bars_do_not_replace_pinned_bitstamp_seed(self):
        rows=evidence(market(),broker(),'BTCUSD','GROWTH',NOW)
        self.assertIn('BITSTAMP',next(d for k,v,d in rows if k=='History/warmup native V1 lengkap'))
        self.assertIsNone(next(v for k,v,d in rows if k=='Setup frozen original / Break40 terpenuhi'))

    def test_market_download_is_not_truncated_at_old_status_size_limit(self):
        content=json.dumps({'bars':[],'padding':'x'*100000}).encode()
        response=MagicMock();response.__enter__.return_value.read.return_value=content
        with patch('fx_scanner.cbot_v1_dashboard.urlopen',return_value=response):
            self.assertEqual(len(fetch_json(MARKET_URL,1)['padding']),100000)
