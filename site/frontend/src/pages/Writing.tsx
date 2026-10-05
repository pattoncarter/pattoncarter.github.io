import { api } from '../api/client'
import { useContent } from '../api/useContent'
import { SectionError } from '../components/SectionError'

export function Writing() {
  const { data, error, loading } = useContent(api.writing)

  if (error) return <main className="mx-auto max-w-5xl px-6 py-16"><SectionError section="writing" error={error} /></main>
  if (loading || !data) return <main className="mx-auto max-w-5xl px-6 py-16 font-mono text-muted">loading…</main>

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-8 px-6 py-16">
      <h1 className="font-display text-3xl font-bold">Writing</h1>
      {data.intro && <p className="max-w-3xl leading-relaxed text-muted">{data.intro}</p>}
      <ul className="flex flex-col gap-4">
        {data.posts.map(post => (
          <li key={post.url}>
            <a
              href={post.url}
              target="_blank"
              rel="noreferrer"
              className="block rounded-md border border-border bg-surface p-5 transition-colors hover:border-accent"
            >
              <h2 className="font-display font-semibold">{post.title}</h2>
              {post.date && <p className="mt-1 font-mono text-xs text-muted">{post.date}</p>}
              {post.excerpt && <p className="mt-2 text-sm text-muted">{post.excerpt}</p>}
            </a>
          </li>
        ))}
      </ul>
      {data.archive_url && (
        <a href={data.archive_url} target="_blank" rel="noreferrer" className="text-sm text-accent hover:underline">
          View All Posts on Substack →
        </a>
      )}
    </main>
  )
}
