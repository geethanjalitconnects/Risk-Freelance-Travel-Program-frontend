import { useEffect, useState } from 'react';
import { Link } from '../router.jsx';
import Logo from './Logo.jsx';
import Icon from './Icon.jsx';
import { useStore } from '../lib/store.js';
import { useAuth } from '../lib/auth.js';

const NAV = [
  { to: '/search', label: 'Find a ride', match: (p) => p.startsWith('/search') || p.startsWith('/ride') },
  { to: '/publish', label: 'Publish a ride', match: (p) => p === '/publish' || p.startsWith('/edit/') },
  { to: '/trips', label: 'My trips', match: (p) => p === '/trips' },
  { to: '/how-it-works', label: 'How it works', match: (p) => p === '/how-it-works' },
  { to: '/risk-program', label: 'Risk program', match: (p) => p === '/risk-program' },
];

export default function Header({ path }) {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 8);
    on();
    window.addEventListener('scroll', on, { passive: true });
    return () => window.removeEventListener('scroll', on);
  }, []);
  const profile = useStore((s) => s.profile);
  const auth = useAuth();
  const active = auth.user?.activeTrips || 0;

  return (
    <header className={'site-header' + (scrolled ? ' scrolled' : '')}>
      <div className="container header-inner">
        <Link to="/" className="brand" aria-label="VConnects home" onClick={() => setOpen(false)}>
          <Logo />
        </Link>
        <nav className={'nav' + (open ? ' open' : '')} aria-label="Main">
          {NAV.map((n) => (
            <Link
              key={n.to}
              to={n.to === '/search' ? '/' : n.to}
              className={'nav-link' + (n.match(path) ? ' active' : '')}
              onClick={() => setOpen(false)}
            >
              {n.label}
              {n.to === '/trips' && active > 0 && <span className="live-dot" title="Trip in progress" />}
            </Link>
          ))}
          {auth.status === 'signed-in' && (
            <Link to="/dashboard" className={'nav-link' + (path === '/dashboard' ? ' active' : '')} onClick={() => setOpen(false)}>Dashboard</Link>
          )}
          {auth.status === 'signed-in' && (
            <Link to="/wallet" className={'nav-link' + (path === '/wallet' ? ' active' : '')} onClick={() => setOpen(false)}>Wallet</Link>
          )}
          {auth.status === 'signed-in' ? (
            <Link to="/profile" className={'nav-link profile-link' + (path === '/profile' ? ' active' : '')} onClick={() => setOpen(false)}>
              <Icon name="user" size={18} />
              {profile.name ? profile.name.split(' ')[0] : 'Profile'}
            </Link>
          ) : (
            <Link
              to={path === '/login' ? '/login' : `/login?next=${encodeURIComponent(path)}`}
              className={'nav-link profile-link' + (path === '/login' ? ' active' : '')}
              onClick={() => setOpen(false)}
            >
              <Icon name="user" size={18} />
              Sign in
            </Link>
          )}
        </nav>
        <button className="menu-btn" aria-label="Toggle menu" aria-expanded={open} onClick={() => setOpen(!open)}>
          <Icon name={open ? 'close' : 'menu'} />
        </button>
      </div>
    </header>
  );
}
