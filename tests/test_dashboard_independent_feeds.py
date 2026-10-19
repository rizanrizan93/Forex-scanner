from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest
from test_manual_reversal_reference import snapshot
from fx_scanner.dashboard_independent_feeds import hierarchy_input, macro_input
from fx_scanner.pre_news_expectation import MACRO_WORKER
from fx_scanner.pre_news_transport import CONTRACT

ROOT = Path(__file__).resolve().parents[1]


def zone_map():
    p = snapshot()
    p['timeframe_fresh'] = {'H1': True, 'H4': True, 'M15': True, 'M5': True}
    return p


def macro_feed():
    at = datetime.now(UTC).isoformat()
    return {'contract': CONTRACT, 'published_at': at, 'execution_authority': False,
            'execution_influence': False, 'heartbeats': [
        {'worker_name': MACRO_WORKER, 'observed_at': at, 'healthy': True,
         'details': {'evaluation': {'components': {'US10Y': {'current': 5.2,
             'previous': 5.23, 'delta': -3, 'freshness': 'FRESH', 'observed_at': at}},
             'intraday_yield_context': {'current': 5.19, 'current_at': at,
                 'available': True, 'gold_implication': 'GOLD_SUPPORT', 'state': 'YIELD_DOWN'}}}}]}


def test_hierarchy_requires_fresh_price_and_keeps_m1_separate_from_m15():
    p = zone_map()
    out = hierarchy_input(p)
    assert out['active_zones'] and all(z['timeframe'] in {'H1', 'H4'} for z in out['active_zones'])
    assert 'latest_m15_close' not in out
    p['latest_closed_m15'] = {'closed_at': p['as_of'], 'close': 101.5}
    assert hierarchy_input(p)['latest_m15_close'] == 101.5
    p['price_observed_at'] = (datetime.now(UTC)-timedelta(hours=1)).isoformat()
    with pytest.raises(ValueError): hierarchy_input(p)


def test_stale_timeframe_zones_and_m15_confirmation_are_excluded():
    p = zone_map()
    p['timeframe_fresh'] = {}
    p['latest_closed_m15'] = {'closed_at': p['as_of'], 'close': 101.5}
    out = hierarchy_input(p)
    assert not out['active_zones'] and 'latest_m15_close' not in out


def test_macro_does_not_require_any_sd_or_executor_heartbeat():
    result = macro_input(macro_feed())
    assert result['evaluation']['components']['US10Y']['current'] == 5.2


def test_fresh_publication_does_not_make_old_intraday_quote_current():
    p = macro_feed()
    quote = p['heartbeats'][0]['details']['evaluation']['intraday_yield_context']
    quote['current_at'] = (datetime.now(UTC)-timedelta(hours=12)).isoformat()
    quote['age_seconds'] = 20
    original = deepcopy(p)
    result = macro_input(p)['evaluation']
    assert result['last_cash_yield']['current'] == 5.19
    assert result['intraday_yield_context']['available'] is False
    assert 'current' not in result['intraday_yield_context']
    assert p == original


@pytest.mark.parametrize('where', ['published_at', 'worker', 'unhealthy'])
def test_bad_macro_source_is_rejected(where):
    p = macro_feed()
    old = (datetime.now(UTC)-timedelta(hours=1)).isoformat()
    if where == 'published_at': p['published_at'] = old
    if where == 'worker': p['heartbeats'][0]['observed_at'] = old
    if where == 'unhealthy': p['heartbeats'][0]['healthy'] = False
    with pytest.raises(ValueError): macro_input(p)


def test_hierarchy_page_renders_without_turso_primary():
    with patch('fx_scanner.manual_reversal_dashboard.fetch_manual_map', new=lambda: zone_map()), \
         patch('fx_scanner.xau_turso_hot_snapshot_v407.fetch_public_hot_snapshot', side_effect=ValueError('primary stale')):
        app = AppTest.from_file(str(ROOT/'pages/0A_RIZAN_Zone_Hierarchy_V406.py')).run()
        assert not app.exception and app.metric
        assert not any('heartbeat' in x.value.lower() or 'snapshot scanner belum' in x.value.lower() for x in app.error)
        assert any('cTrader' in x.value for x in app.caption)


def test_macro_page_renders_without_turso_primary():
    with patch('fx_scanner.pre_news_transport.fetch_pre_news_snapshot', new=lambda: macro_feed()), \
         patch('fx_scanner.xau_turso_hot_snapshot_v407.fetch_public_hot_snapshot', side_effect=ValueError('primary stale')):
        app = AppTest.from_file(str(ROOT/'pages/2_US10Y_Regime_Timing.py')).run()
        assert not app.exception and not app.error
        assert any(x.label == 'FRED DGS10' and x.value == '5.200%' for x in app.metric)


@pytest.mark.parametrize('label', ['Hierarki zona', 'Makro'])
def test_main_tabs_run_independently_of_legacy_imports(label):
    with patch('fx_scanner.manual_reversal_dashboard.fetch_manual_map', new=lambda: zone_map()), \
         patch('fx_scanner.pre_news_transport.fetch_pre_news_snapshot', new=lambda: macro_feed()), \
         patch('fx_scanner.xau_event_dashboard_patch_v377.install_event_macro_dashboard_patch', side_effect=KeyError('old import')):
        app = AppTest.from_file(str(ROOT/'main.py'))
        app.session_state['rizan_xau_detail'] = label
        app.run(timeout=20)
        assert not app.exception and app.metric


def futures_feed(*, stale=False):
    p = macro_feed()
    context = p['heartbeats'][0]['details']['evaluation']['intraday_yield_context']
    context.update(current_at=(datetime.now(UTC)-timedelta(hours=15)).isoformat(),
        effective_source='YAHOO_FINANCE_ZN_FRONT_PROXY',
        state='US10Y_CASH_LAST_VALID_FUTURES_ACTIVE',
        futures_at=(datetime.now(UTC)-timedelta(minutes=25 if stale else 10)).isoformat(),
        futures_price=111.25, futures_change_points=.0625,
        futures_yield_pressure='YIELD_DOWN_PROXY', freshness='PROXY_FRESH')
    return p


def test_recent_futures_restore_timing_without_relabeling_cash_yield():
    result = macro_input(futures_feed())['evaluation']
    active = result['intraday_yield_context']
    assert active['available'] is True and active['current'] is None
    assert active['timing_basis'] == 'TREASURY_FUTURES_PROXY'
    assert active['futures_price'] == 111.25
    assert result['last_cash_yield']['current'] == 5.19
    from fx_scanner.xau_yield_regime_view_v372 import yield_regime_summary
    summary = yield_regime_summary(result)
    assert summary['intraday']['gold_bias'] == 'BULLISH_XAU'
    assert summary['intraday']['current'] is None


def test_stale_futures_never_restore_intraday_even_when_feed_is_new():
    active = macro_input(futures_feed(stale=True))['evaluation']['intraday_yield_context']
    assert active['available'] is False and active['gold_implication'] == 'UNAVAILABLE'


def test_zn_quote_survives_public_feed_projection():
    from fx_scanner.demo_xau_macro_attribution_v357 import build_dashboard_projection
    p = futures_feed()
    evaluation = p['heartbeats'][0]['details']['evaluation']
    out = build_dashboard_projection(evaluation)['intraday_yield_context']
    for key in ['effective_source', 'futures_at', 'futures_price', 'futures_change_points', 'futures_yield_pressure']:
        assert out[key] == evaluation['intraday_yield_context'][key]


def test_proxy_panel_displays_futures_price_and_not_old_cash_as_current_yield():
    import streamlit as st
    st.cache_data.clear()
    with patch('fx_scanner.pre_news_transport.fetch_pre_news_snapshot', new=lambda: futures_feed()):
        app = AppTest.from_file(str(ROOT/'pages/2_US10Y_Regime_Timing.py')).run()
        assert not app.exception
        assert any(x.label == 'Treasury futures ZN · harga proksi' and x.value == '111.250' for x in app.metric)
        assert not any(x.label == 'Yield intraday sekarang' for x in app.metric)
        assert any('Waktu kuotasi ZN' in x.value for x in app.caption)


def test_zone_adapter_preserves_degraded_lifecycle_and_pending_breach():
    p = zone_map()
    parent = next(z for z in p['zones'] if z['timeframe'] == 'H1')
    parent['lifecycle'] = 'DEGRADED'
    parent['touch_count'] = 3
    parent['risk_state'] = 'PENDING_PARENT_CLOSE'
    out = hierarchy_input(p)
    mapped = next(z for z in out['active_zones'] if z['zone_id'] == parent['zone_id'])
    assert mapped['condition'] == 'DEGRADED'
    assert mapped['intraday_quarantined'] is True
    assert mapped['lifecycle']['freshness'] == 'DEGRADED'


def test_us10y_page_still_shows_independent_cash_health_when_macro_feed_stale():
    import streamlit as st
    st.cache_data.clear()
    with patch('fx_scanner.pre_news_transport.fetch_pre_news_snapshot', side_effect=ValueError('stale macro')):
        app = AppTest.from_file(str(ROOT/'pages/2_US10Y_Regime_Timing.py')).run(timeout=20)
    assert not app.exception
    assert any(x.label == 'Source Health' for x in app.metric)
    assert not any(x.label == 'FRED DGS10' for x in app.metric)
    assert any('Feed engine Daily FRED' in x.value for x in app.warning)
