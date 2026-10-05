import pytest
from pydantic import ValidationError

from app.models import AboutContent, ContactInfo, Post, Project, WritingContent


def test_post_optional_fields_default_to_none():
    p = Post(title="T", url="https://x")
    assert p.date is None and p.excerpt is None


def test_project_links_is_dict():
    pr = Project(title="P", description="d", technologies=["a"], links={"repo": "https://r"})
    assert pr.links["repo"] == "https://r"


def test_about_full_construction():
    a = AboutContent(
        tagline="t", hero="h", mission="m", interests="i", quote="q",
        competencies=["c1"],
        education=[{"degree": "BS", "school": "X"}],
        resume_url="https://r",
        socials={"github": "https://g"},
    )
    assert a.competencies == ["c1"]
    assert a.education[0].description == ""


def test_about_missing_required_field_raises():
    with pytest.raises(ValidationError):
        AboutContent(tagline="t")  # everything else missing


def test_contact_minimal():
    c = ContactInfo(email="e@x.com", socials={})
    assert c.email == "e@x.com"


def test_project_optional_fields_default_to_none():
    pr = Project(title="P", description="d")
    assert pr.image_url is None and pr.role is None and pr.status is None
    assert pr.technologies == [] and pr.links == {}


def test_writing_defaults():
    w = WritingContent(posts=[])
    assert w.intro == "" and w.archive_url is None


def test_post_serialization_includes_optional_keys():
    p = Post(title="T", url="https://x")
    assert p.model_dump() == {"title": "T", "url": "https://x", "date": None, "excerpt": None}
