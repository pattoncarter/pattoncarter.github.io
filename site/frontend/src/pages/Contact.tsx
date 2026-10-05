import { api } from '../api/client'
import { useContent } from '../api/useContent'
import { ParticleField } from '../components/ParticleField'
import { SectionError } from '../components/SectionError'

const socialCards: Record<string, { name: string; label: string }> = {
  github: { name: 'GitHub', label: '@pattoncarter' },
  linkedin: { name: 'LinkedIn', label: 'Connect professionally' },
  substack: { name: 'Substack', label: 'Subscribe to my articles' },
}

export function Contact() {
  const { data, error, loading } = useContent(api.contact)

  return (
    <main className="relative mx-auto flex min-h-[70vh] max-w-5xl flex-col justify-center gap-8 overflow-hidden px-6 py-16">
      <ParticleField className="pointer-events-none absolute inset-0 h-full w-full opacity-60" />
      <div className="relative">
        <h1 className="font-display text-3xl font-bold"><span className="text-accent">#</span> CONNECT</h1>
        {error ? (
          <SectionError section="contact" error={error} />
        ) : loading || !data ? (
          <p className="mt-4 font-mono text-muted">loading…</p>
        ) : (
          <>
            {data.intro && (
              <p className="mt-4 max-w-2xl leading-relaxed text-muted">{data.intro}</p>
            )}
            <div className="mt-6">
              <h2 className="font-display text-xl font-bold">Email</h2>
              <a href={`mailto:${data.email}`}
                 className="mt-4 inline-block rounded-md bg-accent px-6 py-3 font-display font-semibold text-bg transition-opacity hover:opacity-80">
                {data.email}
              </a>
            </div>
            <div className="mt-6 flex flex-wrap gap-4">
              {Object.entries(data.socials ?? {}).map(([key, url]) => (
                <a key={key} href={url} target="_blank" rel="noreferrer"
                   className="flex items-center rounded-md border border-border px-6 py-3 transition-colors hover:border-accent">
                  <div>
                    <h3 className="font-display font-semibold">{socialCards[key]?.name ?? key}</h3>
                    <span className="text-sm text-muted">{socialCards[key]?.label}</span>
                  </div>
                </a>
              ))}
            </div>
          </>
        )}
      </div>
    </main>
  )
}
