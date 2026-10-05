export function Footer() {
  return (
    <footer className="border-t border-border py-6">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-2 px-6 font-mono text-xs text-muted">
        <p>
          <span className="text-accent">&lt;</span>CARTER<span className="text-accent">&gt;</span> PATTON
        </p>
        <p>© {new Date().getFullYear()} All Rights Reserved</p>
      </div>
    </footer>
  )
}
