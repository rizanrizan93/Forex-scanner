"""Canonical Streamlit Community Cloud entrypoint.

The dashboard implementation remains in 'streamlit_app.py' so the UI stays
isolated from the scanner/runtime hot path. runpy executes that file on
every Streamlit rerun instead of relying on Python's import cache.
"""

from __future__ import annotations

import runpy
from pathlib import Path

APP = Path(__file__).resolve().with_name("streamlit_app.py")

if not APP.is_file():
    raise RuntimeError(f"Streamlit dashboard implementation is missing: {APP}")

runpy.run_path(str(APP), run_name="__main__")
