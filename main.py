"""Pair tabs with lazy execution and compatible existing page URLs."""
from __future__ import annotations
import runpy
import sys
from pathlib import Path
import streamlit as st
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
st.set_page_config(page_title="RIZAN Scanner", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")

def render_dashboard(default_pair="XAUUSD", default_detail="Zona reversal"):
    st.session_state.setdefault("rizan_pair", default_pair)
    st.session_state.setdefault("rizan_xau_detail", default_detail)
    xau, eurusd, cbots = st.tabs(["XAUUSD", "EURUSD", "cBots"], key="rizan_pair", on_change="rerun")
    if cbots.open:
        with cbots:
            from fx_scanner.cbot_manual_dashboard import render_cbot_manual_dashboard
            render_cbot_manual_dashboard()
    if eurusd.open:
        with eurusd:
            from fx_scanner.selected_raw_reference_dashboard import render_selected_raw_reference
            render_selected_raw_reference("EURUSD")
            from fx_scanner.cross_asset_dashboard import render_cross_asset
            render_cross_asset("EURUSD")
            runpy.run_path(str(ROOT / "pages/00_EURUSD_Demo_Forward.py"), run_name="__main__")
    if xau.open:
        with xau:
            labels = ["Zona reversal", "Setup", "Hierarki zona", "Keputusan", "Demand", "Pre-News", "Makro", "Pengaturan"]
            tabs = st.tabs(labels, key="rizan_xau_detail", on_change="rerun")
            paths = [None, "streamlit_app.py", "pages/0A_RIZAN_Zone_Hierarchy_V406.py", "pages/0_Pusat_Keputusan_XAUUSD.py", "pages/1_Demand_Tiers.py", "pages/3_Pre_News_Expectation.py", "pages/2_US10Y_Regime_Timing.py", "streamlit_app.py"]
            for label, tab, path in zip(labels, tabs, paths):
                if tab.open:
                    with tab:
                        if path is None:
                            from fx_scanner.zone_v05_dashboard import render_zone_v05
                            render_zone_v05()
                        else:
                            # Legacy patches are needed only by the detailed XAU pages.
                            # Keep the manual map and EUR independent of their import graph.
                            if label in {"Setup", "Pengaturan"}:
                                from fx_scanner.xau_event_dashboard_patch_v377 import install_event_macro_dashboard_patch
                                from fx_scanner.xau_whalezone_dashboard_patch_v408 import install_whalezone_dashboard_patch
                                install_event_macro_dashboard_patch()
                                install_whalezone_dashboard_patch()
                            if label == "Setup":
                                from fx_scanner.selected_raw_reference_dashboard import render_selected_raw_reference
                                from fx_scanner.xau_frozen_dd50_dashboard import render_frozen_core
                                from fx_scanner.cross_asset_dashboard import render_cross_asset
                                render_selected_raw_reference("XAUUSD")
                                render_frozen_core()
                                render_cross_asset("XAUUSD")
                            if label in {"Hierarki zona", "Makro"}:
                                @st.fragment(run_every="60s")
                                def independent_panel(path=path):
                                    runpy.run_path(str(ROOT / path), run_name="__main__")
                                independent_panel()
                            else:
                                runpy.run_path(str(ROOT / path), run_name="__main__", init_globals={"RIZAN_SETTINGS_ONLY": label == "Pengaturan"})

routes = [st.Page(render_dashboard, title="RIZAN Scanner", default=True)]
for slug, pair, detail in [("EURUSD_Demo_Forward", "EURUSD", "Setup"), ("RIZAN_Zone_Hierarchy_V406", "XAUUSD", "Hierarki zona"), ("Pusat_Keputusan_XAUUSD", "XAUUSD", "Keputusan"), ("Demand_Tiers", "XAUUSD", "Demand"), ("US10Y_Regime_Timing", "XAUUSD", "Makro")]:
    def route(pair=pair, detail=detail):
        render_dashboard(pair, detail)
    routes.append(st.Page(route, title=slug, url_path=slug))
# Register existing URLs while disabling the automatic sidebar page list.
st.navigation(routes, position="hidden").run()
