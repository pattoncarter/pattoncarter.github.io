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
    # Every project needs an id: the /projects/:id detail route depends on it.
    assert projects and all(p.id for p in projects)
    assert source.get_writing().posts
    assert source.get_contact().email
