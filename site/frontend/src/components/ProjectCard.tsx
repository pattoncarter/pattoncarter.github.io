import { Link } from 'react-router-dom'
import type { Project } from '../api/types'

// Label values match what the live site renders per link type (verified against
// the production bundle's link objects). Same map as the detail page (Task 13A) — keep in sync.
const linkLabels: Record<string, string> = {
  repo: 'GitHub Repository',
  report: 'Report',
  site: 'Coming Soon',
  final_report: 'Final Report',
  final_presentation: 'Final Presentation',
}

export function ProjectCard({ project }: { project: Project }) {
  return (
    <article className="flex flex-col gap-4 rounded-lg border border-border bg-surface p-6">
      {project.image_url && (
        <img src={project.image_url} alt={project.title} className="h-40 w-full rounded-md object-cover" />
      )}
      <div className="flex items-start justify-between gap-3">
        {/* Only the title links (not the whole card) — the link row below contains
            anchors, and wrapping them in a card-level Link would be invalid HTML. */}
        <h3 className="font-display text-lg font-semibold">
          <Link to={project.id ? `/projects/${project.id}` : '/projects'} className="hover:text-accent hover:underline">
            {project.title}
          </Link>
        </h3>
        {project.status && (
          <span className="whitespace-nowrap rounded bg-accent/10 px-2 py-1 font-mono text-xs text-accent">
            {project.status}
          </span>
        )}
      </div>
      <p className="text-sm leading-relaxed">{project.description}</p>
      {project.role && <p className="text-sm leading-relaxed text-muted">{project.role}</p>}
      {project.technologies && project.technologies.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {project.technologies.map(t => (
            <li key={t} className="rounded border border-border px-2 py-1 font-mono text-xs text-muted">{t}</li>
          ))}
        </ul>
      )}
      {project.links && Object.keys(project.links).length > 0 && (
        <div className="mt-auto flex gap-4 pt-2 text-sm">
          {Object.entries(project.links).map(([key, url]) => (
            <a key={key} href={url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
              {linkLabels[key] ?? key}
            </a>
          ))}
        </div>
      )}
    </article>
  )
}
