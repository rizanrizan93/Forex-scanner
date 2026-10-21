"""Persistent dashboard navigation with lazy, isolated page rendering."""
from __future__ import annotations
import runpy
import sys
from pathlib import Path
import streamlit as st
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
st.set_page_config(page_title="RIZAN Scanner", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")
st.markdown(
    """<style>
    /* Legacy EUR/Setup pages reduce .block-container padding to .75rem.
       Reserve space for Streamlit's header so it cannot cover navigation. */
    [data-testid="stMainBlockContainer"] {
        padding-top: 4.5rem !important;
    }
    [data-testid="stLayoutWrapper"]:has(> .st-key-rizan_primary_navigation) {
        position: sticky; top: 3.5rem; z-index: 990;
    }
    .st-key-rizan_primary_navigation {
        background: var(--background-color); padding: .4rem 0;
        border-bottom: 1px solid rgba(128, 128, 128, .2);
    }
    .st-key-rizan_primary_navigation [role="radiogroup"],
    .st-key-rizan_xau_navigation [role="radiogroup"] {
        flex-wrap: wrap; gap: .35rem 1rem;
    }
    </style>""",
    unsafe_allow_html=True,
)

@st.cache_resource(show_spinner=False)
def load_zone_panel(source_revision):
    """Reload the panel once per source revision, including on a running app."""
    from importlib import reload
    from fx_scanner import zone_v05_dashboard
    return reload(zone_v05_dashboard).render_zone_v05

def render_dashboard(default_pair="XAUUSD", default_detail="Zona reversal"):
    st.session_state.setdefault("rizan_pair", default_pair)
    st.session_state.setdefault("rizan_xau_detail", default_detail)
    st.session_state["rizan_xau_detail"] = st.session_state["rizan_xau_detail"]
    # Keep navigation outside legacy page/tab containers. A child page may
    # stop or rerun, but must never own or replace the primary navigation.
    with st.container(key="rizan_primary_navigation"):
        pair = st.radio(
            "Instrumen", ["XAUUSD", "EURUSD", "cBots"],
            key="rizan_pair", horizontal=True, label_visibility="collapsed",
        )
    if pair == "cBots":
        with st.container(key="rizan_cbots_content"):
            from fx_scanner.cbot_manual_dashboard import render_cbot_manual_dashboard
            render_cbot_manual_dashboard()
    if pair == "EURUSD":
        with st.container(key="rizan_eurusd_content"):
            from fx_scanner.selected_raw_reference_dashboard import render_selected_raw_reference
            render_selected_raw_reference("EURUSD")
            from fx_scanner.cross_asset_dashboard import render_cross_asset
            render_cross_asset("EURUSD")
            runpy.run_path(str(ROOT / "pages/00_EURUSD_Demo_Forward.py"), run_name="__main__")
    if pair == "XAUUSD":
        with st.container(key="rizan_xau_content"):
            labels = ["Zona reversal", "Setup", "Hierarki zona", "Keputusan", "Demand", "Pre-News", "Makro", "Pengaturan"]
            # Preserve the last XAU detail across EUR/cBots runs, even though
            # Streamlit cleans up widgets that are not rendered on that run.
            with st.container(key="rizan_xau_navigation"):
                selected_detail = st.radio(
                    "Halaman XAUUSD", labels, key="rizan_xau_detail",
                    horizontal=True, label_visibility="collapsed",
                )
            paths = [None, "streamlit_app.py", "pages/0A_RIZAN_Zone_Hierarchy_V406.py", "pages/0_Pusat_Keputusan_XAUUSD.py", "pages/1_Demand_Tiers.py", "pages/3_Pre_News_Expectation.py", "pages/2_US10Y_Regime_Timing.py", "streamlit_app.py"]
            for label, path in zip(labels, paths):
                if label == selected_detail:
                    with st.container(key="rizan_xau_detail_content"):
                        if path is None:
                            panel_source = ROOT / "src/fx_scanner/zone_v05_dashboard.py"
                            load_zone_panel(panel_source.stat().st_mtime_ns)()
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
