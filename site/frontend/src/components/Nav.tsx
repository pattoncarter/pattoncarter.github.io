import { NavLink } from 'react-router-dom'

const links = [
  { to: '/', label: 'HOME', prefix: '~/' },
  { to: '/about', label: 'ABOUT', prefix: './' },
  { to: '/projects', label: 'PROJECTS', prefix: './' },
  { to: '/writing', label: 'WRITING', prefix: './' },
  { to: '/contact', label: 'CONTACT', prefix: './' },
]

export function Nav() {
  return (
    <header className="sticky top-0 z-10 border-b border-border bg-bg/80 backdrop-blur">
      <nav className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
        <NavLink to="/" className="font-mono text-lg font-bold tracking-wide">
          <span>C:</span>
          <span className="text-accent">/</span>
          <span>P</span>
        </NavLink>
        <div className="flex gap-6 font-mono text-sm">
          {links.map(l => (
            <NavLink
              key={l.to}
              to={l.to}
              className={({ isActive }) =>
                `transition-colors ${isActive ? 'text-accent' : 'text-muted hover:text-text'}`
              }
            >
              <span className="text-accent">{l.prefix}</span>
              {l.label}
            </NavLink>
          ))}
        </div>
      </nav>
    </header>
  )
}
