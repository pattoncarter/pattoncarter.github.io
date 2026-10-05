import { NavLink } from 'react-router-dom'

const links = [
  { to: '/about', label: 'About' },
  { to: '/projects', label: 'Projects' },
  { to: '/writing', label: 'Writing' },
  { to: '/contact', label: 'Contact' },
]

export function Nav() {
  return (
    <header className="sticky top-0 z-10 border-b border-border bg-bg/80 backdrop-blur">
      <nav className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
        <NavLink to="/" className="font-display text-lg font-bold tracking-wide">
          CARTER
        </NavLink>
        <div className="flex gap-6 text-sm">
          {links.map(l => (
            <NavLink
              key={l.to}
              to={l.to}
              className={({ isActive }) =>
                `transition-colors ${isActive ? 'text-accent' : 'text-muted hover:text-text'}`
              }
            >
              {l.label}
            </NavLink>
          ))}
        </div>
      </nav>
    </header>
  )
}
