import type { AboutContent, ContactInfo, Project, WritingContent } from './types'

// GitHub Pages mode: when VITE_STATIC_CONTENT=true (set by `npm run build:pages`),
// serve the content JSONs baked in at build time from site/backend/content/
// instead of fetching from the FastAPI backend. The dynamic imports plus the
// env-replaced constant let rollup drop the unused branch entirely, so the
// normal (Docker) bundle contains no content and the Pages bundle never fetches.
const STATIC_CONTENT = import.meta.env.VITE_STATIC_CONTENT === 'true'

async function fetchJson<T>(path: string): Promise<T> {
  const resp = await fetch(path)
  if (!resp.ok) throw new Error(`${path} responded ${resp.status}: ${(await resp.text()).slice(0, 200)}`)
  return (await resp.json()) as T
}

// Cast at the boundary: TS's inferred JSON types (union members with
// `key?: undefined`) don't fit the wire interfaces exactly. The backend
// validates this same content against pydantic models at runtime.
function baked<T>(load: () => Promise<unknown>): Promise<T> {
  return load().then(m => (m as { default: T }).default)
}

export const api = {
  about: () => STATIC_CONTENT ? baked<AboutContent>(() => import('../../../backend/content/about.json')) : fetchJson<AboutContent>('/api/about'),
  projects: () => STATIC_CONTENT ? baked<Project[]>(() => import('../../../backend/content/projects.json')) : fetchJson<Project[]>('/api/projects'),
  writing: () => STATIC_CONTENT ? baked<WritingContent>(() => import('../../../backend/content/writing.json')) : fetchJson<WritingContent>('/api/writing'),
  contact: () => STATIC_CONTENT ? baked<ContactInfo>(() => import('../../../backend/content/contact.json')) : fetchJson<ContactInfo>('/api/contact'),
}
