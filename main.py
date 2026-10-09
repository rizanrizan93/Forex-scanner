"""Pair tabs with lazy execution and compatible existing page URLs."""
from __future__ import annotations
import runpy
import sys
from pathlib import Path
import streamlit as st
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from fx_scanner.xau_event_dashboard_patch_v377 import install_event_macro_dashboard_patch
from fx_scanner.xau_whalezone_dashboard_patch_v408 import install_whalezone_dashboard_patch
st.set_page_config(page_title="RIZAN Scanner", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")
install_event_macro_dashboard_patch()
install_whalezone_dashboard_patch()

def render_dashboard(default_pair="XAUUSD", default_detail="Setup"):
    st.session_state.setdefault("rizan_pair", default_pair)
    st.session_state.setdefault("rizan_xau_detail", default_detail)
    xau, eurusd = st.tabs(["XAUUSD", "EURUSD"], key="rizan_pair", on_change="rerun")
    if eurusd.open:
        with eurusd:
            runpy.run_path(str(ROOT / "pages/00_EURUSD_Demo_Forward.py"), run_name="__main__")
    if xau.open:
        with xau:
            labels = ["Setup", "Hierarki zona", "Keputusan", "Demand", "Makro", "Pengaturan"]
            tabs = st.tabs(labels, key="rizan_xau_detail", on_change="rerun")
            paths = ["streamlit_app.py", "pages/0A_RIZAN_Zone_Hierarchy_V406.py", "pages/0_Pusat_Keputusan_XAUUSD.py", "pages/1_Demand_Tiers.py", "pages/2_US10Y_Regime_Timing.py", "streamlit_app.py"]
            for label, tab, path in zip(labels, tabs, paths):
                if tab.open:
                    with tab:
                        runpy.run_path(str(ROOT / path), run_name="__main__", init_globals={"RIZAN_SETTINGS_ONLY": label == "Pengaturan"})

routes = [st.Page(render_dashboard, title="RIZAN Scanner", default=True)]
for slug, pair, detail in [("EURUSD_Demo_Forward", "EURUSD", "Setup"), ("RIZAN_Zone_Hierarchy_V406", "XAUUSD", "Hierarki zona"), ("Pusat_Keputusan_XAUUSD", "XAUUSD", "Keputusan"), ("Demand_Tiers", "XAUUSD", "Demand"), ("US10Y_Regime_Timing", "XAUUSD", "Makro")]:
    def route(pair=pair, detail=detail):
        render_dashboard(pair, detail)
    routes.append(st.Page(route, title=slug, url_path=slug))
# Register existing URLs while disabling the automatic sidebar page list.
st.navigation(routes, position="hidden").run()
