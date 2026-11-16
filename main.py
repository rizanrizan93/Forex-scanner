"""Persistent dashboard navigation with lazy, isolated page rendering."""
from __future__ import annotations
import runpy
import sys
from pathlib import Path
import streamlit as st
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
st.set_page_config(page_title="RIZAN Scanner", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")
from fx_scanner.ui_terminal import TERMINAL_CSS, render_brand, render_section_intro
st.markdown(TERMINAL_CSS, unsafe_allow_html=True)

@st.cache_resource(show_spinner=False)
def load_zone_panel(source_revision):
    """Reload the panel once per source revision, including on a running app."""
    from importlib import reload
    from fx_scanner import zone_v05_dashboard
    return reload(zone_v05_dashboard).render_zone_v05

def navigate_pair():
    pair = st.session_state["rizan_pair"]
    detail = st.session_state.get("_rizan_last_xau_detail", "Zona reversal")
    st.session_state["_rizan_pending_route"] = (pair, detail if pair == "XAUUSD" else "Setup")


def navigate_detail():
    detail = st.session_state["rizan_xau_detail"]
    st.session_state["_rizan_last_xau_detail"] = detail
    st.session_state["_rizan_pending_route"] = ("XAUUSD", detail)


def render_dashboard(default_pair="XAUUSD", default_detail="Zona reversal"):
    render_brand(st)
    route = (default_pair, default_detail)
    prior_route = st.session_state.get("_rizan_active_route")
    if prior_route != route:
        if prior_route is None:
            # First load: retain an existing widget selection rather than
            # silently overwriting persisted or AppTest session state.
            st.session_state.setdefault("rizan_pair", default_pair)
            if default_pair == "XAUUSD":
                st.session_state.setdefault("rizan_xau_detail", default_detail)
                st.session_state.setdefault(
                    "_rizan_last_xau_detail", st.session_state["rizan_xau_detail"]
                )
        else:
            # Real navigation to a different Streamlit route owns its target.
            st.session_state["rizan_pair"] = default_pair
            if default_pair == "XAUUSD":
                st.session_state["rizan_xau_detail"] = default_detail
                st.session_state["_rizan_last_xau_detail"] = default_detail
        st.session_state["_rizan_active_route"] = route
    st.session_state.setdefault("rizan_pair", default_pair)
    st.session_state.setdefault("rizan_xau_detail", default_detail)
    # Normalize the two former navigation labels after a live Streamlit reload.
    if st.session_state.get("rizan_xau_detail") in {"USD Lead", "Teknikal", "Checklist", "Teknikal + USD Lead"}:
        st.session_state["rizan_xau_detail"] = "Analisis Terpadu"
    if st.session_state.get("_rizan_last_xau_detail") in {"USD Lead", "Teknikal", "Checklist", "Teknikal + USD Lead"}:
        st.session_state["_rizan_last_xau_detail"] = "Analisis Terpadu"
    # Keep navigation outside legacy page/tab containers. A child page may
    # stop or rerun, but must never own or replace the primary navigation.
    with st.container(key="rizan_primary_navigation"):
        pair = st.radio(
            "Instrumen", ["XAUUSD", "EURUSD", "Frozen V1", "cBots"],
            key="rizan_pair", horizontal=True, label_visibility="collapsed",
            on_change=navigate_pair,
        )
    if pair == "Frozen V1":
        with st.container(key="rizan_frozen_v1_bias_content"):
            render_section_intro(st, pair="Frozen V1", detail="Frozen V1")
            from fx_scanner.frozen_v1_bias_dashboard import render_frozen_v1_bias_dashboard
            render_frozen_v1_bias_dashboard()
    if pair == "cBots":
        with st.container(key="rizan_cbots_content"):
            render_section_intro(st, pair="cBots", detail="cBots")
            from fx_scanner.cbot_v1_dashboard import render_v1_dashboard
            render_v1_dashboard()
    if pair == "EURUSD":
        with st.container(key="rizan_eurusd_content"):
            render_section_intro(st, pair="EURUSD", detail="EURUSD")
            from fx_scanner.selected_raw_reference_dashboard import render_selected_raw_reference
            render_selected_raw_reference("EURUSD")
            from fx_scanner.cross_asset_dashboard import render_cross_asset
            render_cross_asset("EURUSD")
            runpy.run_path(str(ROOT / "pages/00_EURUSD_Demo_Forward.py"), run_name="__main__")
    if pair == "XAUUSD":
        with st.container(key="rizan_xau_content"):
            labels = ["Zona reversal", "Zona A→B", "Setup", "Hierarki zona", "Keputusan", "Analisis Terpadu", "Demand", "Pre-News", "Makro", "Pengaturan"]
            # Preserve the last XAU detail across EUR/cBots runs, even though
            # Streamlit cleans up widgets that are not rendered on that run.
            with st.container(key="rizan_xau_navigation"):
                selected_detail = st.radio(
                    "Halaman XAUUSD", labels, key="rizan_xau_detail",
                    horizontal=True, label_visibility="collapsed",
                    on_change=navigate_detail,
                )
            paths = [None, None, "streamlit_app.py", "pages/0A_RIZAN_Zone_Hierarchy_V406.py", "pages/0_Pusat_Keputusan_XAUUSD.py", "pages/7_XAU_Unified_Decision.py", "pages/1_Demand_Tiers.py", "pages/3_Pre_News_Expectation.py", "pages/2_US10Y_Regime_Timing.py", "streamlit_app.py"]
            render_section_intro(st, pair="XAUUSD", detail=selected_detail)
            for label, path in zip(labels, paths):
                if label == selected_detail:
                    with st.container(key="rizan_xau_detail_content"):
                        if path is None:
                            if label == "Zona A→B":
                                from fx_scanner.predictive_zone_dashboard import render_predictive_zone_dashboard
                                render_predictive_zone_dashboard()
                            else:
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
                                # M15 forecast must update within the first minutes
                                # of a candle, rather than wait for a 60s UI rerun.
                                interval = "15s" if label == "Makro" else "60s"
                                @st.fragment(run_every=interval)
                                def independent_panel(path=path, label=label):
                                    with st.spinner("Memperbarui " + label + "…"):
                                        runpy.run_path(str(ROOT / path), run_name="__main__")
                                independent_panel()
                            else:
                                runpy.run_path(str(ROOT / path), run_name="__main__", init_globals={"RIZAN_SETTINGS_ONLY": label == "Pengaturan"})

def render_cbot_webview():
    from fx_scanner.cbot_webview_dashboard import render_webview_plugin
    render_webview_plugin()



def protected_dashboard(pair="XAUUSD", detail="Zona reversal"):
    # Control-flow exceptions (stop/rerun/switch_page) inherit BaseException and
    # are deliberately NOT swallowed. Real page errors retain navigation.
    try:
        with st.spinner("Memuat " + pair + " · " + detail + "…"):
            render_dashboard(pair, detail)
    except Exception:
        st.error("Halaman belum dapat dimuat. Pilih tab lain atau coba muat ulang.")
        if st.button("Coba muat ulang", key="rizan_retry_page"):
            st.rerun()


PAGES = {}
ROUTE_SPECS = [
    ("", "XAUUSD", "Zona reversal"),
    ("EURUSD_Demo_Forward", "EURUSD", "Setup"),
    ("cbots", "cBots", "Setup"),
    ("Frozen_V1", "Frozen V1", "Setup"),
    ("Zona_Prediktif_XAUUSD", "XAUUSD", "Zona A→B"),
    ("XAU_Setup", "XAUUSD", "Setup"),
    ("RIZAN_Zone_Hierarchy_V406", "XAUUSD", "Hierarki zona"),
    ("Pusat_Keputusan_XAUUSD", "XAUUSD", "Keputusan"),
    ("XAU_Analisis_Terpadu", "XAUUSD", "Analisis Terpadu"),
    # Keep old deep links while routing every research view to one panel.
    ("XAU_Decision_Checklist", "XAUUSD", "Analisis Terpadu"),
    ("USD_Lead_Engine", "XAUUSD", "Analisis Terpadu"),
    ("XAU_Technical_Engine", "XAUUSD", "Analisis Terpadu"),
    ("Demand_Tiers", "XAUUSD", "Demand"),
    ("Pre_News", "XAUUSD", "Pre-News"),
    ("US10Y_Regime_Timing", "XAUUSD", "Makro"),
    ("XAU_Settings", "XAUUSD", "Pengaturan"),
]
routes = []
for slug, pair, detail in ROUTE_SPECS:
    def route(pair=pair, detail=detail):
        protected_dashboard(pair, detail)
    # Every panel has a distinct registered page. Switching pages cancels the
    # old script and its timed fragments instead of reusing their UI slots.
    page = st.Page(route, title=slug or "RIZAN Scanner", url_path=slug or None,
                   default=not slug)
    # The second URL is a backward-compatible alias; navigation uses the first.
    PAGES.setdefault((pair, detail), page)
    routes.append(page)
routes.append(st.Page(render_cbot_webview, title="RIZAN cBot Plugin", url_path="cbot-plugin"))
active_page = st.navigation(routes, position="hidden")
pending_route = st.session_state.pop("_rizan_pending_route", None)
if pending_route is not None:
    # Run outside widget callbacks: rerun/switch requests inside a callback
    # can be ignored by Streamlit and leave the previous page on screen.
    st.switch_page(PAGES[pending_route])
active_page.run()
