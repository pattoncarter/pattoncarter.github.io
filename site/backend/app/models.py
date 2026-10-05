from pydantic import BaseModel


class Education(BaseModel):
    degree: str
    school: str
    description: str = ""


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
