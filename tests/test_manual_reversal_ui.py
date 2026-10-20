import json,sys
from pathlib import Path
from datetime import UTC,datetime,timedelta
from streamlit.testing.v1 import AppTest
from test_manual_reversal_reference import snapshot


def render(p):
    root=str(Path(__file__).resolve().parents[1]/'src')
    source=f"import sys,json\nsys.path.insert(0,{root!r})\nfrom fx_scanner.manual_reversal_dashboard import render_snapshot\nrender_snapshot(json.loads({json.dumps(p)!r}))\n"
    return AppTest.from_string(source).run(timeout=15)


def test_manual_panel_renders_both_directions_and_only_reference_widgets():
    app=render(snapshot())
    assert not app.exception
    assert any(x.label=='Area acuan H1' for x in app.metric)
    assert len(app.button)==0 and len(app.checkbox)==0
    assert any('Kandidat demand' in x.value for x in app.markdown)
    assert any('Kandidat supply' in x.value for x in app.markdown)
    assert any('Probabilitas reversal' in x.value for x in app.caption)


def test_stale_prices_are_hidden_instead_of_rendered_as_current_reference():
    p=snapshot();p['price_observed_at']=(datetime.now(UTC)-timedelta(hours=1)).isoformat()
    app=render(p)
    assert not app.exception and not app.metric
    assert app.warning and 'kedaluwarsa' in app.warning[0].value


def test_candidate_a_research_watch_shows_non_executable_1r_reference():
    p=snapshot()
    p['plans'][0]['candidate_a']={
        'model':'CANDIDATE_A_TP1R_WATCH','state':'WATCH',
        'reason':'SEMUA_FILTER_TERKONFIRMASI',
        'first_touch_at':p['as_of'],'zone_age_at_first_touch_minutes':20,
        'confirmation_lag_minutes':20,'d1_bias':'BEARISH',
        'd1_closed_at':p['as_of'],'ema20':100.,'ema50':101.,
        'entry_reference':102.,'sl_reference':97.9,'tp_1r_reference':106.1,
        'rr_reference':1.0,'execution_authority':False,
        'execution_influence':False,'probability':None}
    app=render(p)
    assert not app.exception
    assert any('WATCH' in x.value and 'bukan izin order' in x.value for x in app.info)
    assert any(x.label=='TP 1R skenario' for x in app.metric)
    assert not app.button and not app.checkbox
