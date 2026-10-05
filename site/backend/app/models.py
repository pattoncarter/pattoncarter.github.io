"""Wire contract for /api/<section>. Keep in sync with frontend src/api/types.ts."""
from pydantic import BaseModel


class Education(BaseModel):
    degree: str
    school: str
    description: str = ""
    date_range: str | None = None


class AboutContent(BaseModel):
    tagline: str
    hero: str
    mission: str
    interests: str
    quote: str
    competencies: list[str]
    education: list[Education]
    resume_url: str
    socials: dict[str, str]


class Project(BaseModel):
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


class Post(BaseModel):
    title: str
    url: str
    date: str | None = None
    excerpt: str | None = None


class WritingContent(BaseModel):
    intro: str = ""
    posts: list[Post]
    archive_url: str | None = None


class ContactInfo(BaseModel):
    email: str
    socials: dict[str, str] = {}
    intro: str | None = None
