"""Check published entry points and documentation references without API calls."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_published_document_links_resolve():
    documents = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
    for document in documents:
        content = document.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)]+)\)", content):
            if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
                continue
            path = target.split("#", 1)[0]
            assert (document.parent / path).is_file(), f"{document.name}: {target}"


def test_readme_quick_start_entry_points_exist():
    content = (ROOT / "README.md").read_text(encoding="utf-8")
    modules = re.findall(r"python -m ([a-zA-Z_][\w.]*)", content)
    assert modules, "Quick start must contain a runnable Python module"
    for module in modules:
        assert (ROOT / (module.replace(".", "/") + ".py")).is_file()
    assert (ROOT / "启动拾光.cmd").is_file()
