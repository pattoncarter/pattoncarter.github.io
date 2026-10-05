import pytest
from pydantic import ValidationError

from app.models import AboutContent, ContactInfo, Education, Post, Project, WritingContent


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


def test_project_detail_fields_optional():
    p = Project(title="T", description="D")
    assert p.id is None
    assert p.long_description is None
    assert p.highlights == []
    assert p.insights is None
    assert p.timeline is None
    assert p.category is None


def test_project_detail_fields_populated():
    p = Project.model_validate({
        "id": "ghidrapt", "title": "T", "description": "D",
        "long_description": "Para one.\n\nPara two.",
        "highlights": ["h1", "h2"], "insights": "text",
        "timeline": "Jan 2024 - Jun 2024", "category": "AI",
        "technologies": [], "links": {},
    })
    assert p.id == "ghidrapt"
    assert p.highlights == ["h1", "h2"]
    assert p.long_description == "Para one.\n\nPara two."
    assert p.insights == "text"
    assert p.timeline == "Jan 2024 - Jun 2024"
    assert p.category == "AI"


def test_education_date_range_optional():
    e = Education(degree="B.S.", school="S")
    assert e.date_range is None
    e2 = Education(degree="B.S.", school="S", date_range="2020 - 2024")
    assert e2.date_range == "2020 - 2024"


def test_contact_intro_optional():
    c = ContactInfo(email="a@b.c", socials={})
    assert c.intro is None
    c2 = ContactInfo(email="a@b.c", socials={}, intro="hi")
    assert c2.intro == "hi"


def test_unknown_key_rejected():
    with pytest.raises(ValidationError):
        Project.model_validate({"title": "T", "description": "D", "higlights": []})
