import { useEffect, useState } from 'react';

// Tiny hash router: keeps the project dependency-free and works on any static host.
export function parseHash() {
  const raw = window.location.hash.replace(/^#/, '') || '/';
  const [path, qs = ''] = raw.split('?');
  return { path: path || '/', query: Object.fromEntries(new URLSearchParams(qs)) };
}

export function useRoute() {
  const [route, setRoute] = useState(parseHash());
  useEffect(() => {
    const onChange = () => {
      setRoute(parseHash());
      window.scrollTo(0, 0);
    };
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return route;
}

export function navigate(path, query) {
  const qs = query ? '?' + new URLSearchParams(query).toString() : '';
  window.location.hash = path + qs;
}

// In-page scroll that respects reduced motion. A hash link like "#find" can't be used: this
// router reads the hash as the route, so it would open a "find" page (404).
export function scrollToId(id, focusSelector) {
  const el = document.getElementById(id);
  if (!el) return false;
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
  const target = focusSelector && el.querySelector(focusSelector);
  if (target) target.focus({ preventScroll: true });
  return true;
}

export function Link({ to, children, ...rest }) {
  return (
    <a href={'#' + to} {...rest}>
      {children}
    </a>
  );
}
