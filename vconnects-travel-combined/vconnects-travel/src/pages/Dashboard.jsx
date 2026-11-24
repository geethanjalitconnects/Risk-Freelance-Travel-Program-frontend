import { Link } from '../router.jsx';
import { cityByCode } from '../data/cities.js';
import { fmtDateTime, fmtPrice } from '../lib/format.js';
import { useAuth } from '../lib/auth.js';
import { listBookings, myRides } from '../lib/ridesApi.js';
import { useApi } from '../lib/useApi.js';
import Icon from '../components/Icon.jsx';
import VerificationBanner from '../components/VerificationBanner.jsx';
import { getVerification } from '../lib/verificationApi.js';

const cityName = (code) => cityByCode(code)?.name || code;

function Stat({ label, value }) {
  return <div className="stat"><strong>{value}</strong><span>{label}</span></div>;
}

function Body({ userId, name }) {
  const bookings = useApi(listBookings, [userId]);
  const rides = useApi(myRides, [userId]);
  const verification = useApi(getVerification, [userId]);
  const b = bookings.data || [];
  const r = rides.data || [];
  const upcoming = b.filter((x) => x.status === 'confirmed' || x.status === 'in_progress');
  const completed = b.filter((x) => x.status === 'completed');
  const spent = completed.reduce((s, x) => s + Number(x.total || 0), 0);
  const loading = bookings.loading || rides.loading;
  const error = bookings.error || rides.error;

  return (
    <div className="container page info-page">
      <span className="tag">Dashboard</span>
      <h1 className="page-title">Welcome back{name ? `, ${name.split(' ')[0]}` : ''}</h1>
      <VerificationBanner v={verification.data} />

      {error && <p className="callout warn">{error.message} <button className="btn btn-sm btn-ghost" onClick={() => { bookings.reload(); rides.reload(); }}>Retry</button></p>}
      {loading && !error && <p className="muted">Loading your activity…</p>}

      {!loading && !error && (
        <>
          <div className="stats">
            <Stat label="Upcoming trips" value={upcoming.length} />
            <Stat label="Trips completed" value={completed.length} />
            <Stat label="Rides published" value={r.length} />
            <Stat label="Spent on completed trips" value={fmtPrice(spent)} />
          </div>

          <h2 className="sub">Upcoming trips</h2>
          {upcoming.length === 0 ? (
            <div className="panel empty"><p>No upcoming trips.</p><Link to="/" className="btn btn-accent">Find a ride</Link></div>
          ) : upcoming.map((x) => (
            <article key={x.id} className="panel dash-row">
              <div>
                <h3>{cityName(x.ride.from)} → {cityName(x.ride.to)}</h3>
                <p className="muted">{fmtDateTime(x.ride.depart)} · {x.seats} seat{x.seats > 1 ? 's' : ''} · {x.ride.driver.name}</p>
              </div>
              <span className={'status-tag st-' + x.status}>{x.status.replace('_', ' ')}</span>
            </article>
          ))}

          <h2 className="sub">Your published rides</h2>
          {r.length === 0 ? (
            <div className="panel empty"><p>You have not published a ride yet.</p><Link to="/publish" className="btn btn-ghost">Offer a ride</Link></div>
          ) : r.slice(0, 5).map((x) => (
            <article key={x.id} className="panel dash-row">
              <div>
                <h3>{cityName(x.from)} → {cityName(x.to)}</h3>
                <p className="muted">{fmtDateTime(x.depart)} · {x.seatsTotal - x.seatsLeft}/{x.seatsTotal} seats booked · {fmtPrice(x.price)}/seat</p>
              </div>
              <Link to={`/ride/${encodeURIComponent(x.id)}`} className="btn btn-sm btn-ghost">View</Link>
            </article>
          ))}

          <div className="cta-row">
            <Link to="/trips" className="btn btn-primary">All my trips <Icon name="arrow" size={16} /></Link>
            <Link to="/profile" className="btn btn-ghost">Profile &amp; contacts</Link>
          </div>
        </>
      )}
    </div>
  );
}

export default function Dashboard() {
  const auth = useAuth();
  if (auth.status === 'loading') return <div className="container page"><p className="muted">Loading…</p></div>;
  if (auth.status !== 'signed-in') {
    return (
      <div className="container page empty">
        <h2>Sign in to see your dashboard</h2>
        <Link to="/login?next=/dashboard" className="btn btn-accent">Sign in or sign up</Link>
      </div>
    );
  }
  return <Body userId={auth.user.id} name={auth.user.name} />;
}
