import pytest

from app.sources import _REGISTRY, get_source_for_section
from app.sources.json_source import ContentError, JsonFileSource


@pytest.fixture
def content_dir(tmp_path):
    d = tmp_path / "content"
    d.mkdir()
    (d / "writing.json").write_text(
        '{"intro": "hi", "posts": [{"title": "P1", "url": "https://p1"}], '
        '"archive_url": null}'
    )
    return d


def test_json_source_get_writing(content_dir):
    source = JsonFileSource(content_dir)
    writing = source.get_writing()
    assert writing.posts[0].title == "P1"
    assert writing.intro == "hi"


def test_json_source_missing_file_raises(content_dir):
    with pytest.raises(ContentError, match="about"):
        JsonFileSource(content_dir).get_about()


def test_json_source_invalid_json_raises(content_dir):
    (content_dir / "writing.json").write_text("{not json")
    with pytest.raises(ContentError, match="invalid"):
        JsonFileSource(content_dir).get_writing()


def test_json_source_validation_error_raises(content_dir):
    # Parses as JSON but fails the pydantic model -> still a ContentError
    (content_dir / "writing.json").write_text('{"posts": "not-a-list"}')
    with pytest.raises(ContentError, match="invalid"):
        JsonFileSource(content_dir).get_writing()


def test_json_source_projects_scalar_root_raises(content_dir):
    (content_dir / "projects.json").write_text("42")
    with pytest.raises(ContentError, match="invalid"):
        JsonFileSource(content_dir).get_projects()


def test_unknown_source_name_raises(monkeypatch):
    monkeypatch.setenv("WRITING_SOURCE", "nope")
    with pytest.raises(ValueError, match="nope"):
        get_source_for_section("writing")


def test_registered_fake_source_selected(monkeypatch):
    from app.models import WritingContent

    class FakeSource:
        def get_writing(self):
            return WritingContent(posts=[])

    monkeypatch.setitem(_REGISTRY, "fake", lambda d: FakeSource())
    monkeypatch.setenv("WRITING_SOURCE", "fake")
    assert isinstance(get_source_for_section("writing"), FakeSource)
