// NOTE: optionality mirrors the pydantic wire format exactly — fields with
// defaults in backend/app/models.py are ALWAYS present in JSON (required here),
// and nullable fields are always present with a possibly-null value.

export interface Education {
  degree: string
  school: string
  description: string
  date_range: string | null
}

export interface AboutContent {
  tagline: string
  hero: string
  mission: string
  interests: string
  quote: string
  competencies: string[]
  education: Education[]
  resume_url: string
  socials: Record<string, string>
}

export interface Project {
  id: string | null
  title: string
  description: string
  long_description: string | null
  highlights: string[]
  insights: string | null
  timeline: string | null
  category: string | null
  technologies: string[]
  links: Record<string, string>
  image_url: string | null
  role: string | null
  status: string | null
}

export interface Post {
  title: string
  url: string
  date: string | null
  excerpt: string | null
}

export interface WritingContent {
  intro: string
  posts: Post[]
  archive_url: string | null
}

export interface ContactInfo {
  email: string
  intro: string | null
  socials: Record<string, string>
}
