"""Wire contract for /api/<section>. Keep in sync with frontend src/api/types.ts."""
from pydantic import BaseModel, ConfigDict


class ContentModel(BaseModel):
    """Content contract: unknown keys are data errors, not silently ignored."""
    model_config = ConfigDict(extra="forbid")


class Education(ContentModel):
    degree: str
    school: str
    description: str = ""
    date_range: str | None = None


class AboutContent(ContentModel):
    tagline: str
    hero: str
    mission: str
    interests: str
    quote: str
    competencies: list[str]
    education: list[Education]
    resume_url: str
    socials: dict[str, str]


class Project(ContentModel):
    title: str
    description: str
    technologies: list[str] = []
    links: dict[str, str] = {}
    image_url: str | None = None
    role: str | None = None
    status: str | None = None  # e.g. "IN PROGRESS"
    id: str | None = None
    long_description: str | None = None
    highlights: list[str] = []
    insights: str | None = None
    timeline: str | None = None
    category: str | None = None


class Post(ContentModel):
    title: str
    url: str
    date: str | None = None
    excerpt: str | None = None


class WritingContent(ContentModel):
    intro: str = ""
    posts: list[Post]
    archive_url: str | None = None


class ContactInfo(ContentModel):
    email: str
    socials: dict[str, str] = {}
    intro: str | None = None
