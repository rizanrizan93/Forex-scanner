from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def test_pair_tabs_only_execute_selected_page():
    with patch("runpy.run_path") as execute, patch("fx_scanner.xau_public_hot_v362.fetch_public_hot_snapshot", return_value={"heartbeats": []}):
        app = AppTest.from_file(str(ROOT / "main.py"))
        app.run()
        assert not app.exception
        assert {"XAUUSD", "EURUSD"}.issubset({tab.label for tab in app.tabs})
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
