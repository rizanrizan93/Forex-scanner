"""Independent XAU technical engine; no execution access."""
import sys
from pathlib import Path
from datetime import UTC, datetime
import streamlit as st
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT/'src') not in sys.path:
    sys.path.insert(0,str(ROOT/'src'))
from fx_scanner.xau_decision_candle_feed_v1 import fetch_decision_candles
from fx_scanner.xau_technical_engine_v1 import evaluate_technical, compare_macro
from fx_scanner.ui_terminal import render_condition
from fx_scanner.pre_news_transport import fetch_pre_news_snapshot
from fx_scanner.dashboard_independent_feeds import macro_input
from fx_scanner.usd_lead_decision_v1 import evaluate_usd_lead
from fx_scanner.xau_yield_pressure_nowcast_v1 import evaluate_yield_pressure

@st.fragment(run_every='60s')
def render():
    now=datetime.now(UTC)
    st.subheader('XAU Technical Engine V1 · SMC / ICT')
    st.caption('Candle cTrader tertutup H1/M15/M5 · evaluasi 60 detik · riset manual, akurasi belum diuji out-of-sample.')
    feed, error={}, None
    try:
        feed=fetch_decision_candles(now=now)
    except Exception as exc:
        error=type(exc).__name__+': '+str(exc)
    report=evaluate_technical(feed,now=now)
    st.metric('Arah teknikal',report['direction'])
    st.caption('Sumber: cTrader market data read-only · observasi snapshot '+str(feed.get('as_of') or 'belum tersedia'))
    if error:
        st.warning('WAIT DATA · '+error)
    for side, tab in zip(('BUY','SELL'),st.tabs(['Checklist BUY','Checklist SELL'])):
        with tab:
            r=report[side]
            st.write(str(r['passed'])+'/6 terpenuhi · '+r['state'])
            for item in r['items']:
                render_condition(st,title=item['name'],state=item['state'],detail=item['why'])
            if r['plan']:
                p=r['plan']
                st.write('Referensi close %.2f · invalidasi %.2f · target likuiditas %.2f · %.2fR sebelum biaya' % (p['reference_close'],p['invalidation'],p['target_liquidity'],p['rr_before_costs']))
                st.caption('FVG %.2f–%.2f · evaluasi ulang sebelum %s. Harga referensi candle; spread/slippage belum dihitung.' % (*p['fvg'],p['valid_until']))
    st.markdown('### Konfluensi makro + teknikal')
    try:
        snapshot=fetch_pre_news_snapshot(now=now,timeout_seconds=7.)
        ev=macro_input(snapshot,now=now)['evaluation']
        y=evaluate_yield_pressure(ev,now=now)
        usd=evaluate_usd_lead(ev,now=now,yield_nowcast=y)
        st.write(compare_macro(report,usd,y))
        st.caption('USD '+usd['usd_direction']+' · yield '+y['yield_direction']+' · '+y['state']+'. Hanya feed makro tervalidasi; lihat USD Lead untuk sumber cadangan dan checklist lengkap.')
    except Exception as exc:
        st.info('WAIT — sumber makro belum valid: '+type(exc).__name__)
    st.caption('Aturan deterministik: swing H1 2-kiri/2-kanan; range M15 31 candle observasi lintas sesi tanpa mengisi jeda pasar; sweep → displacement MSS → FVG → retest M5. Setup harus memenuhi semua syarat. Data hilang/gap M5/stale = UNKNOWN; kondisi valid yang belum cocok = FAIL. Engine ini belum memiliki hasil backtest atau tingkat kemenangan terukur.')
render()
