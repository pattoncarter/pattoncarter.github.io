import { useEffect, useState } from 'react'

export function useContent<T>(loader: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    let cancelled = false
    loader()
      .then(d => { if (!cancelled) setData(d) })
      .catch(e => { if (!cancelled) setError(e) })
    return () => { cancelled = true }
    // loaders in api/client.ts are stable module-level functions
  }, [loader])

  return { data, error }
}
