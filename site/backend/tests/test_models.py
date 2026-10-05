import pytest

from app.models import AboutContent, ContactInfo, Post, Project


def test_post_optional_fields_default_to_none():
    p = Post(title="T", url="https://x")
    assert p.date is None and p.excerpt is None


def test_project_links_is_dict():
    pr = Project(title="P", description="d", technologies=["a"], links={"repo": "https://r"})
    assert pr.links["repo"] == "https://r"


def test_about_requires_core_fields():
    a = AboutContent(
        tagline="t", hero="h", mission="m", interests="i", quote="q",
        competencies=["c1"], education=[], resume_url="https://r",
        socials={"github": "https://g"},
    )
    assert a.competencies == ["c1"]


def test_about_missing_required_field_raises():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AboutContent(tagline="t")  # everything else missing


def test_contact_minimal():
    c = ContactInfo(email="e@x.com", socials={})
    assert c.email == "e@x.com"
