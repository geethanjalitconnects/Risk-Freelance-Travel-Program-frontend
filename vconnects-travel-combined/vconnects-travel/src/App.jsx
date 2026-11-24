import { Suspense, lazy, useEffect, useState } from 'react';
import { useRoute } from './router.jsx';
import Preloader from './components/Preloader.jsx';
import CursorDot from './components/CursorDot.jsx';
import RoadBg from './components/RoadBg.jsx';
import Header from './components/Header.jsx';
import Footer from './components/Footer.jsx';
import Home from './pages/Home.jsx';
import Search from './pages/Search.jsx';
import RideDetail from './pages/RideDetail.jsx';
import Publish from './pages/Publish.jsx';
import Trips from './pages/Trips.jsx';
import RiskProgram from './pages/RiskProgram.jsx';
import Profile from './pages/Profile.jsx';
import Login from './pages/Login.jsx';
import DriverVerification from './pages/DriverVerification.jsx';
import About from './pages/About.jsx';
import HowItWorks from './pages/HowItWorks.jsx';
import Safety from './pages/Safety.jsx';
import Help from './pages/Help.jsx';
import Contact from './pages/Contact.jsx';
import Legal from './pages/Legal.jsx';
import Dashboard from './pages/Dashboard.jsx';
import PayoutDetails from './pages/PayoutDetails.jsx';
import Wallet from './pages/Wallet.jsx';
import './pages.css';

// The admin dashboard (/admin/*) is a separate, lazy-loaded chunk: regular users never download it.
const AdminApp = lazy(() => import('./admin/AdminApp.jsx'));
const isAdminPath = (path) => path === '/admin' || path.startsWith('/admin/');

function Page({ path, query }) {
  if (path === '/') return <Home />;
  if (path === '/search') return <Search query={query} />;
  if (path.startsWith('/ride/')) return <RideDetail id={decodeURIComponent(path.slice(6))} />;
  if (path === '/publish') return <Publish />;
  if (path.startsWith('/edit/')) return <Publish key={path} editId={decodeURIComponent(path.slice(6))} />;
  if (path === '/trips') return <Trips />;
  if (path === '/risk-program') return <RiskProgram />;
  if (path === '/profile') return <Profile />;
  if (path === '/login') return <Login query={query} />;
  if (path === '/verification') return <DriverVerification />;
  if (path === '/payout-details') return <PayoutDetails />;
  if (path === '/wallet') return <Wallet query={query} />;
  if (path === '/about') return <About />;
  if (path === '/how-it-works') return <HowItWorks />;
  if (path === '/safety') return <Safety />;
  if (path === '/help') return <Help />;
  if (path === '/contact') return <Contact />;
  if (path === '/terms') return <Legal kind="terms" />;
  if (path === '/privacy') return <Legal kind="privacy" />;
  if (path === '/dashboard') return <Dashboard />;
  return (
    <div className="container page empty">
      <h2>Page not found</h2>
      <a className="btn btn-primary" href="#/">Go home</a>
    </div>
  );
}

export default function App() {
  const { path, query } = useRoute();
  if (isAdminPath(path)) {
    return (
      <Suspense fallback={<p style={{ padding: 24 }}>Loading…</p>}>
        <AdminApp path={path} query={query} />
      </Suspense>
    );
  }
  return <UserApp path={path} query={query} />;
}

function UserApp({ path, query }) {
  const reduce = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let seen = false;
  try { seen = sessionStorage.getItem('vc-intro') === '1'; } catch (e) { /* storage blocked */ }
  const [intro, setIntro] = useState(path === '/' && !seen && !reduce);

  // `intro-done` triggers the hero entrance animations once the orange panel starts lifting.
  useEffect(() => {
    if (!intro) document.documentElement.classList.add('intro-done');
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { document.documentElement.classList.toggle('is-home', path === '/'); }, [path]);

  return (
    <>
      {intro && (
        <Preloader
          onReveal={() => document.documentElement.classList.add('intro-done')}
          onDone={() => { try { sessionStorage.setItem('vc-intro', '1'); } catch (e) { /* ignore */ } setIntro(false); }}
        />
      )}
      <RoadBg />
      <CursorDot />
      <a href="#main" className="skip">Skip to content</a>
      <Header path={path} />
      <main id="main">
        <Page path={path} query={query} />
      </main>
      <Footer />
    </>
  );
}
