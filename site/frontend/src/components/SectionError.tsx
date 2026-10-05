export function SectionError({ section, error }: { section: string; error: unknown }) {
  return (
    <div className="rounded-lg border border-red-900/50 bg-red-950/20 p-6 text-sm text-red-300">
      <p className="font-mono">error :: failed to load {section}</p>
      <p className="mt-2 text-muted">{String(error)}</p>
    </div>
  )
}
