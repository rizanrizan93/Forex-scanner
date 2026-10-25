"""A dedicated WebView route on the existing public scanner host."""
from datetime import UTC,datetime
from pathlib import Path
import json
from .cbot_webview import build_view,safe_json

ROOT=Path(__file__).resolve().parents[2]/'webview_app'

def document(live,demo,*,theme='dark'):
    css=(ROOT/'style.css').read_text()
    contract=(ROOT/'contract.js').read_text().replace('export function ','function ')
    app=(ROOT/'app.js').read_text()
    template=(ROOT/'index.html').read_text()
    return template.replace('__THEME__','light' if theme=='light' else 'dark').replace('__STYLE__',css).replace('__CODE__',contract+'\n'+app).replace('__DATA__',safe_json({'live':live,'demo':demo}))

def demo_view():
    p=json.loads((ROOT/'demo.json').read_text())
    at=datetime.fromisoformat(p['as_of'].replace('Z','+00:00'))
    return build_view(p,now=at,demo=True)

def render_webview_plugin():
    import streamlit as st
    import streamlit.components.v1 as components
    from .cbot_manual_dashboard import fetch
    st.markdown('''<style>header[data-testid="stHeader"], [data-testid="stToolbar"],footer {display:none!important;} .stMainBlockContainer{padding:.2rem!important;max-width:none!important;} .stApp{background:#08111e;}</style>''',unsafe_allow_html=True)
    theme=str(st.query_params.get('theme','dark'))
    symbol=str(st.query_params.get('symbol','XAUUSD'))
    @st.fragment(run_every='10s')
    def panel():
        try:live=build_view(fetch(),symbol=symbol)
        except Exception:live=build_view({},symbol=symbol);live.update(status='FEED_TIDAK_TERSEDIA',reason='Feed belum dapat dibaca. Mencoba ulang otomatis.')
        components.html(document(live,demo_view(),theme=theme),height=1080,scrolling=True)
    panel()
