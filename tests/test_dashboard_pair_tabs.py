from pathlib import Path
from unittest.mock import patch
import sys
from types import ModuleType

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def test_pair_tabs_only_execute_selected_page():
    with patch("runpy.run_path") as execute, patch("fx_scanner.xau_public_hot_v362.fetch_public_hot_snapshot", return_value={"heartbeats": []}):
        app = AppTest.from_file(str(ROOT / "main.py"))
        app.session_state["rizan_xau_detail"] = "Setup"
        app.run()
        assert not app.exception
        assert app.radio[0].options == ["XAUUSD", "EURUSD", "cBots"]
        assert not app.sidebar.children
        assert any("Inti XAUUSD" in item.value for item in app.subheader)
        assert any(m.label == "Executor DEMO" for m in app.metric)
        assert Path(execute.call_args.args[0]).name == "streamlit_app.py"
        execute.reset_mock()
        app.session_state["rizan_pair"] = "EURUSD"
        app.run()
        assert not app.exception
        execute.assert_called_once()
        assert Path(execute.call_args.args[0]).name == "00_EURUSD_Demo_Forward.py"


def test_settings_are_a_subtab():
    with patch("runpy.run_path") as execute, patch("fx_scanner.xau_public_hot_v362.fetch_public_hot_snapshot", return_value={"heartbeats": []}):
        app = AppTest.from_file(str(ROOT / "main.py"))
        app.session_state["rizan_xau_detail"] = "Pengaturan"
        app.run()
        assert not app.exception
        assert execute.call_args.kwargs["init_globals"]["RIZAN_SETTINGS_ONLY"]


def test_navigation_survives_nested_page_stop_and_pair_roundtrip():
    """Exercise real widget changes, child tabs/st.stop, and widget cleanup."""
    import streamlit as st

    modules = {}
    renderers = {
        "xau_event_dashboard_patch_v377": {"install_event_macro_dashboard_patch": lambda: None},
        "xau_whalezone_dashboard_patch_v408": {"install_whalezone_dashboard_patch": lambda: None},
        "selected_raw_reference_dashboard": {"render_selected_raw_reference": lambda symbol: st.caption(symbol)},
        "xau_frozen_dd50_dashboard": {"render_frozen_core": lambda: st.caption("Frozen core")},
        "cross_asset_dashboard": {"render_cross_asset": lambda symbol: None},
        "cbot_manual_dashboard": {"render_cbot_manual_dashboard": lambda: st.caption("cBots panel")},
    }
    package = ModuleType("fx_scanner")
    package.__path__ = []
    modules["fx_scanner"] = package
    for name, functions in renderers.items():
        module = ModuleType("fx_scanner." + name)
        module.__dict__.update(functions)
        modules[module.__name__] = module
        setattr(package, name, module)

    def legacy_page(path, **kwargs):
        with st.tabs(["Setup interne", "Diagnostik interne"])[0]:
            st.caption(Path(path).name)
        st.stop()

    with patch.dict(sys.modules, modules), patch("runpy.run_path", side_effect=legacy_page) as execute:
        app = AppTest.from_file(str(ROOT / "main.py"))
        app.session_state["rizan_xau_detail"] = "Setup"
        app.run()
        assert not app.exception
        assert app.radio[0].options == ["XAUUSD", "EURUSD", "cBots"]
        assert app.radio[1].value == "Setup"

        app.radio[0].set_value("EURUSD").run()
        assert not app.exception
        assert app.radio[0].options == ["XAUUSD", "EURUSD", "cBots"]
        assert app.radio[0].value == "EURUSD"
        assert Path(execute.call_args.args[0]).name == "00_EURUSD_Demo_Forward.py"

        app.radio[0].set_value("cBots").run()
        assert not app.exception
        assert any(item.value == "cBots panel" for item in app.caption)

        app.radio[0].set_value("XAUUSD").run()
        assert not app.exception
        assert app.radio[1].value == "Setup"
        app.radio[1].set_value("Pengaturan").run()
        assert not app.exception
        assert execute.call_args.kwargs["init_globals"]["RIZAN_SETTINGS_ONLY"]
        assert app.radio[0].options == ["XAUUSD", "EURUSD", "cBots"]
