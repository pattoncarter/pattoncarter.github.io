import { api } from '../api/client'
import { useContent } from '../api/useContent'
import { SectionError } from '../components/SectionError'

export function About() {
  const { data, error, loading } = useContent(api.about)

  if (error) return <main className="mx-auto max-w-5xl px-6 py-16"><SectionError section="about" error={error} /></main>
  if (loading || !data) return <main className="mx-auto max-w-5xl px-6 py-16 font-mono text-muted">loading…</main>

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-12 px-6 py-16">
      <h1 className="font-display text-3xl font-bold">About Me</h1>

      <section>
        <h2 className="font-display text-xl font-bold">My Mission</h2>
        {data.mission.split('\n\n').map((p, i) => <p key={i} className="mt-4 max-w-3xl leading-relaxed first:mt-0">{p}</p>)}
        <a
          href={data.resume_url}
          target="_blank"
          rel="noreferrer"
          className="mt-6 w-fit rounded-md bg-accent px-6 py-3 font-display font-semibold text-bg transition-opacity hover:opacity-80"
        >
          View Résumé
        </a>
      </section>

      <section>
        <h2 className="font-display text-xl font-bold">Education</h2>
        <div className="mt-4 flex flex-col gap-4">
          {data.education.map(e => (
            <article key={e.degree} className="rounded-md border border-border bg-surface p-5">
              <h3 className="font-display font-semibold">{e.degree}</h3>
              {e.date_range && <p className="mt-1 font-mono text-xs text-muted">{e.date_range}</p>}
              <p className="text-sm text-muted">{e.school}</p>
              {e.description && <p className="mt-2 text-sm leading-relaxed">{e.description}</p>}
            </article>
          ))}
        </div>
      </section>

      <section>
        <h2 className="font-display text-xl font-bold">Beyond the Code</h2>
        <p className="mt-4 max-w-3xl leading-relaxed text-muted">{data.interests}</p>
      </section>

      <section>
        <h2 className="font-display text-xl font-bold">Core Competencies</h2>
        <ul className="mt-4 grid gap-3 sm:grid-cols-2">
          {data.competencies.map(c => (
            <li key={c} className="rounded-md border border-border bg-surface px-4 py-3 text-sm">{c}</li>
          ))}
        </ul>
      </section>

      <div>
        <p className="font-mono text-sm text-accent">$ cat philosophy.txt</p>
        <blockquote className="mt-2 border-l-2 border-accent pl-4 font-display italic text-muted">
          “{data.quote}”
        </blockquote>
      </div>
    </main>
  )
}
