import { useEffect, useState } from 'react'

export function useContent<T>(loader: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    loader()
      .then(d => { if (!cancelled) { setData(d); setLoading(false) } })
      .catch(e => { if (!cancelled) { setError(e); setLoading(false) } })
    return () => { cancelled = true }
    // Pass a stable module-level loader (e.g. `api.about` from api/client.ts),
    // never an inline closure — an inline arrow changes identity every render
    // and would refetch on every render.
  }, [loader])

  return { data, error, loading }
}
