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

export function Link({ to, children, ...rest }) {
  return (
    <a href={'#' + to} {...rest}>
      {children}
    </a>
  );
}
