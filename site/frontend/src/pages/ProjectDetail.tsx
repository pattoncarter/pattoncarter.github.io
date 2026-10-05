import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useContent } from '../api/useContent'
import { SectionError } from '../components/SectionError'

// Label values match what the live site renders per link type (verified against
// the production bundle's link objects). Same map as ProjectCard (Task 13) — keep in sync.
const linkLabels: Record<string, string> = {
  repo: 'GitHub Repository',
  report: 'Report',
  site: 'Coming Soon',
  final_report: 'Final Report',
  final_presentation: 'Final Presentation',
}

export function ProjectDetail() {
  const { id } = useParams<{ id: string }>()
  const { data, error, loading } = useContent(api.projects)

  if (error) return <main className="mx-auto max-w-5xl px-6 py-16"><SectionError section="projects" error={error} /></main>
  if (loading || !data) return <main className="mx-auto max-w-5xl px-6 py-16 font-mono text-muted">loading…</main>

  const project = data.find(p => p.id === id)
  if (!project) {
    return (
      <main className="mx-auto flex max-w-5xl flex-col gap-4 px-6 py-16">
        <p className="font-mono text-muted">Project not found.</p>
        <Link to="/projects" className="w-fit text-sm text-accent hover:underline">← Back to Projects</Link>
      </main>
    )
  }

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-8 px-6 py-16">
      <Link to="/projects" className="w-fit text-sm text-accent hover:underline">← Back to Projects</Link>
      {project.image_url && (
        <img src={project.image_url} alt={project.title} className="h-64 w-full rounded-lg object-cover" />
      )}
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-display text-3xl font-bold">{project.title}</h1>
        {project.category && (
          <span className="rounded bg-accent/10 px-2 py-1 font-mono text-xs text-accent">{project.category}</span>
        )}
      </div>
      {project.timeline && <p className="font-mono text-sm text-muted">{project.timeline}</p>}
      <p className="max-w-3xl leading-relaxed">{project.description}</p>
      {project.long_description && (
        <div className="flex max-w-3xl flex-col gap-4 leading-relaxed">
          {project.long_description.split('\n\n').map((para, i) => <p key={i}>{para}</p>)}
        </div>
      )}
      {project.role && (
        <section>
          <h2 className="font-display text-xl font-bold">My Role</h2>
          <p className="mt-2 max-w-3xl leading-relaxed">{project.role}</p>
        </section>
      )}
      {project.highlights && project.highlights.length > 0 && (
        <section>
          <h2 className="font-display text-xl font-bold">Project Highlights</h2>
          <ul className="mt-4 flex flex-col gap-3">
            {project.highlights.map(h => (
              <li key={h} className="rounded-md border border-border bg-surface px-4 py-3 text-sm leading-relaxed">{h}</li>
            ))}
          </ul>
        </section>
      )}
      {project.insights && (
        <section>
          <h2 className="font-display text-xl font-bold">Insights &amp; Learnings</h2>
          <p className="mt-2 max-w-3xl leading-relaxed">{project.insights}</p>
        </section>
      )}
      {project.technologies && project.technologies.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {project.technologies.map(t => (
            <li key={t} className="rounded border border-border px-2 py-1 font-mono text-xs text-muted">{t}</li>
          ))}
        </ul>
      )}
      {project.links && Object.keys(project.links).length > 0 && (
        <div className="flex flex-wrap gap-4 text-sm">
          {Object.entries(project.links).map(([key, url]) => (
            <a key={key} href={url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
              {linkLabels[key] ?? key}
            </a>
          ))}
        </div>
      )}
    </main>
  )
}
