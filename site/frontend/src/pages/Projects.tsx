import { api } from '../api/client'
import { useContent } from '../api/useContent'
import { ProjectCard } from '../components/ProjectCard'
import { SectionError } from '../components/SectionError'

export function Projects() {
  const { data, error, loading } = useContent(api.projects)

  if (error) return <main className="mx-auto max-w-5xl px-6 py-16"><SectionError section="projects" error={error} /></main>
  if (loading || !data) return <main className="mx-auto max-w-5xl px-6 py-16 font-mono text-muted">loading…</main>

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-8 px-6 py-16">
      <h1 className="font-display text-3xl font-bold"><span className="text-accent">#</span> PROJECTS</h1>
      <div className="grid gap-6 md:grid-cols-2">
        {data.map(p => <ProjectCard key={p.id ?? p.title} project={p} />)}
      </div>
      <a href="https://github.com/pattoncarter" target="_blank" rel="noreferrer" className="text-sm text-accent hover:underline">
        View More Projects on GitHub
      </a>
    </main>
  )
}
