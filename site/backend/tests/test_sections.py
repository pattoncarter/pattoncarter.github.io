import json

from app.models import AboutContent, ContactInfo, Post, Project, WritingContent
from app.sources import _REGISTRY

ABOUT = {
    "tagline": "Architecting Resilient Futures",
    "hero": "Building at the intersection of AI, cybersecurity, and human potential.",
    "mission": "m", "interests": "i", "quote": "q",
    "competencies": ["c1"], "education": [],
    "resume_url": "https://r", "socials": {"github": "https://g"},
}

WRITING = {
    "intro": "hi",
    "posts": [{"title": "P1", "url": "https://p1"}],
    "archive_url": None,
}

PROJECTS = [{
    "title": "PR", "description": "d", "technologies": [], "links": {},
    "image_url": None, "role": None, "status": None,
}]

CONTACT = {"email": "e@x.com", "socials": {}}


def test_about_returns_validated_content(client, tmp_path):
    (tmp_path / "content" / "about.json").write_text(json.dumps(ABOUT))
    resp = client.get("/api/about")
    assert resp.status_code == 200
    assert resp.json()["tagline"] == ABOUT["tagline"]


def test_about_malformed_json_is_500_and_health_still_ok(client, tmp_path):
    (tmp_path / "content" / "about.json").write_text("{not json")
    resp = client.get("/api/about")
    assert resp.status_code == 500
    assert "about.json" in resp.text
    assert client.get("/api/health").status_code == 200


def test_bad_about_does_not_affect_writing(client, tmp_path):
    (tmp_path / "content" / "about.json").write_text("{not json")
    (tmp_path / "content" / "writing.json").write_text(json.dumps(WRITING))
    assert client.get("/api/about").status_code == 500
    assert client.get("/api/writing").status_code == 200


def test_writing_served_from_json_file(client, tmp_path):
    (tmp_path / "content" / "writing.json").write_text(json.dumps(WRITING))
    resp = client.get("/api/writing")
    assert resp.status_code == 200
    assert resp.json()["posts"][0]["title"] == "P1"


def test_writing_missing_file_is_500(client):
    # conftest seeds only about.json
    resp = client.get("/api/writing")
    assert resp.status_code == 500
    assert "writing.json" in resp.text


def test_projects_served_from_json_file(client, tmp_path):
    (tmp_path / "content" / "projects.json").write_text(json.dumps(PROJECTS))
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert resp.json()[0]["title"] == "PR"


def test_contact_served_from_json_file(client, tmp_path):
    (tmp_path / "content" / "contact.json").write_text(json.dumps(CONTACT))
    resp = client.get("/api/contact")
    assert resp.status_code == 200
    assert resp.json()["email"] == "e@x.com"


class _FakeSource:
    def get_projects(self):
        return [Project(title="FAKE", description="d")]

    def get_contact(self):
        return ContactInfo(email="fake@x.com")
    def get_about(self):
        return AboutContent(
            tagline="FAKE", hero="h", mission="m", interests="i", quote="q",
            competencies=[], education=[], resume_url="https://r", socials={},
        )
    def get_writing(self):
        return WritingContent(posts=[Post(title="FAKE", url="https://fake")])


def test_registered_fake_source_serves_any_section(client, monkeypatch):
    monkeypatch.setitem(_REGISTRY, "fake", lambda content_dir: _FakeSource())
    for section in ("about", "projects", "writing", "contact"):
        monkeypatch.setenv(f"{section.upper()}_SOURCE", "fake")
    assert client.get("/api/writing").json()["posts"][0]["title"] == "FAKE"
    assert client.get("/api/about").json()["tagline"] == "FAKE"
    assert client.get("/api/projects").json()[0]["title"] == "FAKE"
    assert client.get("/api/contact").json()["email"] == "fake@x.com"
