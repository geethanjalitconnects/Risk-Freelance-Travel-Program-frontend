// The admin dashboard: every /admin/* route. Lazy-loaded from App.jsx, so none of this code is in
// the bundle regular users download. The route guard here is only for the UX; the API checks the
// admin token and role on every request.
import { useEffect } from 'react';
import { navigate } from '../router.jsx';
import { getSession, logout, useAdminSession } from './adminApi.js';
import AdminLogin from './pages/AdminLogin.jsx';
import ChangePassword from './pages/ChangePassword.jsx';
import Queue from './pages/Queue.jsx';
import Review from './pages/Review.jsx';
import Audit from './pages/Audit.jsx';
import './admin.css';

function Redirect({ to }) {
  useEffect(() => navigate(to), [to]);
  return null;
}

function Shell({ admin, path, children }) {
  const tab = (to, label) => (
    <a href={'#' + to} className={'adm-tab' + (path.startsWith(to) ? ' on' : '')}>{label}</a>
  );
  return (
    <div className="adm">
      <header className="adm-bar">
        <a className="adm-brand" href="#/admin/queue">VConnects <span>Admin</span></a>
        <nav className="adm-nav" aria-label="Admin">
          {tab('/admin/queue', 'Review queue')}
          {admin.role === 'admin' && tab('/admin/audit', 'Audit log')}
        </nav>
        <div className="adm-who">
          <span title={admin.role}>{admin.name || admin.username} · {admin.role}</span>
          <button className="btn btn-ghost btn-sm" onClick={logout}>Sign out</button>
        </div>
      </header>
      <main className="adm-main">{children}</main>
    </div>
  );
}

export default function AdminApp({ path, query }) {
  useAdminSession(); // re-render on sign-in / sign-out
  useEffect(() => {
    document.title = 'VConnects Admin';
    const robots = document.createElement('meta');
    robots.name = 'robots';
    robots.content = 'noindex, nofollow';
    document.head.appendChild(robots);
    return () => robots.remove();
  }, []);

  const session = getSession();
  if (path === '/admin/login') {
    if (session) return <Redirect to={session.admin.mustChangePassword ? '/admin/password' : query.next || '/admin/queue'} />;
    return <AdminLogin next={query.next} />;
  }
  if (!session) return <Redirect to={'/admin/login?next=' + encodeURIComponent(path)} />;

  const admin = session.admin;
  if (admin.mustChangePassword && path !== '/admin/password') return <Redirect to="/admin/password" />;
  if (path === '/admin/password') return <ChangePassword forced={admin.mustChangePassword} />;

  let page;
  if (path === '/admin' || path === '/admin/' || path === '/admin/queue') page = <Queue query={query} />;
  else if (path.startsWith('/admin/review/')) page = <Review key={path} userId={decodeURIComponent(path.slice(14))} admin={admin} />;
  else if (path === '/admin/audit' && admin.role === 'admin') page = <Audit query={query} />;
  else page = <div className="adm-empty"><h2>Page not found</h2><a href="#/admin/queue">Back to the review queue</a></div>;
  return <Shell admin={admin} path={path}>{page}</Shell>;
}
