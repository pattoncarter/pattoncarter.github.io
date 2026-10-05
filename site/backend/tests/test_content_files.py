"""Guard: the committed content/*.json must always validate against the models.

The rest of the suite is hermetic (tmp_path fixtures); this points the real
JsonFileSource at the real content dir so a typo'd key or type slip in the
seeded data fails locally instead of surfacing as a logged 500 per request.
"""
from pathlib import Path

from app.sources.json_source import JsonFileSource

CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"


def test_real_content_files_validate():
    source = JsonFileSource(CONTENT_DIR)
    assert source.get_about().education
    projects = source.get_projects()
    assert projects, "projects.json is empty"
    # Every project needs a unique id: the /projects/:id detail route depends on it.
    missing = [p.title for p in projects if not p.id]
    assert not missing, f"projects without id: {missing}"
    ids = [p.id for p in projects]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"duplicate project ids: {dupes}"
    assert source.get_writing().posts
    assert source.get_contact().email
