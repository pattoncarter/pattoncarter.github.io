import type { AboutContent, ContactInfo, Project, WritingContent } from './types'

async function fetchJson<T>(path: string): Promise<T> {
  const resp = await fetch(path)
  if (!resp.ok) throw new Error(`${path} responded ${resp.status}`)
  return (await resp.json()) as T
}

export const api = {
  about: () => fetchJson<AboutContent>('/api/about'),
  projects: () => fetchJson<Project[]>('/api/projects'),
  writing: () => fetchJson<WritingContent>('/api/writing'),
  contact: () => fetchJson<ContactInfo>('/api/contact'),
}
