import { api } from '../api/client'
import { useContent } from '../api/useContent'
import { ParticleField } from '../components/ParticleField'
import { SectionError } from '../components/SectionError'

const socialLabels: Record<string, string> = { github: '@pattoncarter', linkedin: 'Connect professionally', substack: 'Subscribe to my articles' }

export function Contact() {
  const { data, error, loading } = useContent(api.contact)

  return (
    <main className="relative mx-auto flex min-h-[70vh] max-w-5xl flex-col justify-center gap-8 overflow-hidden px-6 py-16">
      <ParticleField className="pointer-events-none absolute inset-0 h-full w-full opacity-60" />
      <div className="relative">
        <h1 className="font-display text-3xl font-bold">Contact</h1>
        {error ? (
          <SectionError section="contact" error={error} />
        ) : loading || !data ? (
          <p className="mt-4 font-mono text-muted">loading…</p>
        ) : (
          <>
            {data.intro && (
              <p className="mt-4 max-w-2xl leading-relaxed text-muted">{data.intro}</p>
            )}
            <div className="mt-6 flex flex-wrap gap-4">
              <a href={`mailto:${data.email}`} className="rounded-md bg-accent px-6 py-3 font-display font-semibold text-bg transition-opacity hover:opacity-80">
                {data.email}
              </a>
              {Object.entries(data.socials ?? {}).map(([key, url]) => (
                <a key={key} href={url} target="_blank" rel="noreferrer"
                   className="rounded-md border border-border px-6 py-3 font-display font-semibold transition-colors hover:border-accent">
                  {socialLabels[key] ?? key}
                </a>
              ))}
            </div>
          </>
        )}
      </div>
    </main>
  )
}
