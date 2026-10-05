import { api } from '../api/client'
import { useContent } from '../api/useContent'
import { ParticleField } from '../components/ParticleField'
import { SectionError } from '../components/SectionError'

export function Home() {
  const { data, error, loading } = useContent(api.about)

  return (
    <main className="relative isolate flex min-h-screen items-center justify-center overflow-hidden py-20">
      <ParticleField className="absolute inset-0 h-full w-full" />
      <div className="relative z-10 mx-auto max-w-4xl px-4 text-center">
        <h1 className="mb-6 font-display text-4xl font-bold leading-tight md:text-6xl">
          Carter Patton.{' '}
          <span className="text-accent">Innovator,</span>{' '}
          <span className="text-accent">Leader,</span>{' '}
          <span className="text-accent">Technologist</span>
        </h1>
        <p className="mb-8 font-mono text-lg text-text/80 md:text-xl">
          <span className="text-accent">$ ./Carter-Patton</span>
          <span aria-hidden className="ml-1 inline-block h-5 w-2 translate-y-0.5 animate-blink bg-accent" />
        </p>
        {error ? (
          <SectionError section="home" error={error} />
        ) : loading || !data ? (
          <p className="font-mono text-muted">loading…</p>
        ) : (
          <div className="mx-auto mb-8 max-w-2xl">
            <p className="text-lg">{data.hero}</p>
          </div>
        )}
      </div>
    </main>
  )
}
