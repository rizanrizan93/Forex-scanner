import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_root_streamlit_main_file_exists_and_is_syntax_valid():
    path = ROOT / "streamlit_app.py"
    assert path.is_file()
    source = path.read_text(encoding="utf-8")
    ast.parse(source)
    assert "st.set_page_config" in source
    assert "Main file: streamlit_app.py" in source


def test_streamlit_entrypoint_does_not_import_research_validation_hot_work():
    tree = ast.parse((ROOT / "streamlit_app.py").read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert not any(
        name == "fx_scanner.validation" or name.startswith("fx_scanner.validation.")
        for name in imported
    )


def test_streamlit_dependency_is_pinned_and_no_backend_secret_is_committed():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    assert "streamlit==1.62.0" in requirements
    assert "sb_secret_" not in source
    assert "SUPABASE_SECRET_KEY" in source
    assert "SUPABASE_SERVICE_ROLE_KEY" in source
