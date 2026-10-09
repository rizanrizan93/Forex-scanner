"""Canonical Streamlit Community Cloud entrypoint.

The dashboard implementation remains in 'streamlit_app.py' so the UI stays
isolated from the scanner/runtime hot path. runpy executes that file on
every Streamlit rerun instead of relying on Python's import cache.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

# Streamlit Community Cloud installs requirements.txt but does not necessarily
# install this repository as a package. The project uses a src/ layout, so make
# the package root explicit before importing any fx_scanner module.
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fx_scanner.xau_event_dashboard_patch_v377 import (  # noqa: E402
    install_event_macro_dashboard_patch,
)
from fx_scanner.xau_whalezone_dashboard_patch_v408 import (  # noqa: E402
    install_whalezone_dashboard_patch,
)

APP = ROOT / "streamlit_app.py"

if not APP.is_file():
    raise RuntimeError(f"Streamlit dashboard implementation is missing: {APP}")

# Presentation patches only: raw event numerics remain floats/None and V408
# consumes existing causal zone geometry without adding execution authority.
install_event_macro_dashboard_patch()
install_whalezone_dashboard_patch()
runpy.run_path(str(APP), run_name="__main__")
