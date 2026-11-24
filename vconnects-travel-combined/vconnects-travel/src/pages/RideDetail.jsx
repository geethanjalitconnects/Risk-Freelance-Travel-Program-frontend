import { useEffect, useState } from 'react';
import { Link, navigate } from '../router.jsx';
import { cityByCode } from '../data/cities.js';
import { VEHICLE_FEATURES } from '../lib/risk.js';
import { fmtDateTime, fmtDuration, fmtPrice, fmtTime, toIsoLocal } from '../lib/format.js';
import { useStore } from '../lib/store.js';
import { useAuth } from '../lib/auth.js';
import { createBooking, getRide } from '../lib/ridesApi.js';
import { fmtPlate } from '../lib/verificationApi.js';
import { useApi } from '../lib/useApi.js';
import { getPriceQuote, payForBooking } from '../lib/checkout.js';
import { fmtPaise } from '../lib/walletApi.js';
import Avatar from '../components/Avatar.jsx';
import Icon from '../components/Icon.jsx';
import Modal from '../components/Modal.jsx';
import RiskBadge from '../components/RiskBadge.jsx';
import RiskBreakdown from '../components/RiskBreakdown.jsx';
import PassengerList from '../components/PassengerList.jsx';
import { DriverBadges, Rating } from '../components/DriverTrust.jsx';

export default function RideDetail({ id }) {
  const auth = useAuth();
  const contacts = useStore((s) => s.profile.contacts);
  // Re-fetch when the viewer changes: isOwn, canBook and myBookingId depend on who is looking.
  const { data: ride, error, loading, reload } = useApi(() => getRide(id), [id, auth.status, auth.user?.id]);
  const [seats, setSeats] = useState(1);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [bookErr, setBookErr] = useState('');
  const [quote, setQuote] = useState(null);
  const [held, setHeld] = useState(null); // booking created, waiting for payment

  if (loading && !ride) return <div className="container page"><p className="muted">Loading ride…</p></div>;
  if (error || !ride) {
    const missing = !error || error.status === 404;
    return (
      <div className="container page empty">
        <h2>{missing ? 'Ride not found' : 'Couldn’t load this ride'}</h2>
        <p>{missing ? 'It may have been removed.' : error.message}</p>
        {missing ? <Link to="/" className="btn btn-primary">Back to search</Link> : <button className="btn btn-primary" onClick={reload}>Try again</button>}
      </div>
    );
  }

  const from = cityByCode(ride.from);
  const to = cityByCode(ride.to);
  const signedIn = auth.status === 'signed-in';
  const departed = ride.depart <= toIsoLocal(new Date());
  const maxSeats = Math.max(1, Math.min(4, ride.seatsLeft));
  const n = Math.min(seats, maxSeats);
  const high = ride.risk.band.key === 'high' || ride.risk.band.key === 'elevated';
  const noContacts = contacts.length === 0;

  async function book() {
    setBusy(true);
    setBookErr('');
    try {
      const b = held || await createBooking(ride.id, n);
      if (b.status !== 'pending_payment') return navigate('/trips'); // payments switched off
      setHeld(b);
      await payForBooking(b.id);
      navigate('/trips');
    } catch (e) {
      setBookErr(e.dismissed
        ? 'Payment not completed. Your seats are held for a few minutes: try again, or finish from My trips.'
        : e.message);
      if (!e.dismissed && !held) reload();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="container page detail">
      <Link to="/" className="back" onClick={(e) => { e.preventDefault(); window.history.back(); }}>← Back to results</Link>
      <div className="detail-grid">
        <div className="detail-main">
          <section className="panel">
            <p className="muted">{fmtDateTime(ride.depart)}</p>
            <div className="timeline">
              <div className="tl-stop">
                <strong>{fmtTime(ride.depart)}</strong>
                <div><b>{from?.name}</b><span>{ride.pickup}</span></div>
              </div>
              <div className="tl-gap">{fmtDuration(ride.durationMin)} · {ride.km} km</div>
              <div className="tl-stop">
                <strong>{fmtTime(ride.arrive)}</strong>
                <div><b>{to?.name}</b><span>{ride.dropoff}</span></div>
              </div>
            </div>
            <div className="chips">
              {ride.ac && <span className="chip">Air-conditioned</span>}
              <span className="chip">{ride.bags}</span>
              {ride.travelWith === 'women' && <span className="chip chip-pink">Women only</span>}
              {ride.travelWith === 'men' && <span className="chip">Men only</span>}
            </div>
            {ride.notes && <p className="note">“{ride.notes}”</p>}
          </section>

          <section className="panel">
            <h3>Driver</h3>
            <div className="driver-row">
              <Avatar name={ride.driver.name} size={56} />
              <div>
                <div className="rc-name">{ride.driver.name}</div>
                <div className="rc-sub"><Rating driver={ride.driver} /> <DriverBadges driver={ride.driver} /></div>
                <p className="muted">Member since {ride.driver.since} · {ride.driver.trips} trips · Speaks {ride.driver.langs.join(', ')}</p>
              </div>
            </div>
            {ride.driver.bio && <p>{ride.driver.bio}</p>}
            <h4>Vehicle</h4>
            <p>{ride.vehicle.model} ({ride.vehicle.year}){ride.vehicle.number && <> · <b>{fmtPlate(ride.vehicle.number)}</b></>}</p>
            <div className="chips">
              {ride.vehicle.features.length === 0 && <span className="chip chip-warn">No safety extras listed</span>}
              {ride.vehicle.features.map((f) => <span key={f} className="chip chip-ok">{VEHICLE_FEATURES[f]}</span>)}
            </div>
          </section>

          {ride.isOwn && (
            <section className="panel">
              <h3>Passengers</h3>
              <PassengerList passengers={ride.passengers} />
            </section>
          )}

          <section className="panel">
            <RiskBreakdown risk={ride.risk} />
          </section>
        </div>

        <aside className="book-card">
          <div className="rc-price big">{fmtPrice(ride.price)}<small>/seat</small></div>
          <RiskBadge risk={ride.risk} />
          <p className="muted">{ride.seatsLeft} of {ride.seatsTotal} seats left</p>
          {ride.myBookingId ? (
            <>
              <p className="ok-note"><Icon name="check" size={16} /> You have booked this ride.</p>
              <Link to="/trips" className="btn btn-primary block">Go to My trips</Link>
            </>
          ) : ride.isOwn ? (
            <>
              <p className="muted">This is a ride you published.</p>
              {!departed && <Link to={`/edit/${encodeURIComponent(ride.id)}`} className="btn btn-ghost block">Edit ride</Link>}
            </>
          ) : !signedIn ? (
            <Link to={`/login?next=${encodeURIComponent('/ride/' + ride.id)}`} className="btn btn-accent block">Sign in to book</Link>
          ) : !ride.canBook ? (
            <p className="muted">{ride.cannotBookReason}{ride.cannotBookCode === 'travel_with' && !auth.user?.gender && <> <Link to="/profile">Open profile</Link></>}</p>
          ) : (
            <>
              <div className="sf-field">
                <span>Seats</span>
                <div className="stepper">
                  <button type="button" onClick={() => setSeats(Math.max(1, n - 1))} aria-label="Fewer seats">−</button>
                  <output>{n}</output>
                  <button type="button" onClick={() => setSeats(Math.min(maxSeats, n + 1))} aria-label="More seats">+</button>
                </div>
              </div>
              <div className="total"><span>Total</span><b>{fmtPrice(ride.price * n)}</b></div>
              <button className="btn btn-accent block" onClick={() => { setBookErr(''); setConfirm(true); }}>Book {n} seat{n > 1 ? 's' : ''}</button>
              <p className="fine">No payment is taken in the app.</p>
            </>
          )}
        </aside>
      </div>

      {confirm && (
        <Modal title="Confirm your booking" onClose={() => setConfirm(false)}>
          <p><b>{from?.name} → {to?.name}</b>, {fmtDateTime(ride.depart)}</p>
          <p>{n} seat{n > 1 ? 's' : ''} · Driver {ride.driver.name}</p>
          <PriceBreakdown rideId={ride.id} seats={n} onQuote={setQuote} />
          <p><RiskBadge risk={ride.risk} /></p>
          {high && <p className="callout warn">This trip has a {ride.risk.band.label.toLowerCase()} risk score. Review the tips on this page and keep check-ins on.</p>}
          {noContacts && (
            <p className="callout">
              You have no trusted contacts yet. <Link to="/profile">Add one in your profile</Link> so check-ins and SOS have someone to reach.
            </p>
          )}
          {bookErr && <p className="form-error" role="alert">{bookErr}</p>}
          <div className="modal-actions">
            <button className="btn btn-ghost" onClick={() => setConfirm(false)}>Cancel</button>
            <button className="btn btn-accent" onClick={book} disabled={busy || (Boolean(bookErr) && !held)}>
              {busy ? 'Opening payment…' : quote?.paymentsEnabled ? (held ? 'Try payment again' : `Pay ${fmtPaise(quote.total)}`) : 'Confirm booking'}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}


// Ride amount + VConnects platform fee = total, from the server (all maths there).
function PriceBreakdown({ rideId, seats, onQuote }) {
  const [q, setQ] = useState(null);
  useEffect(() => {
    let alive = true;
    getPriceQuote(rideId, seats).then((x) => { if (alive) { setQ(x); onQuote(x); } }).catch(() => {});
    return () => { alive = false; };
  }, [rideId, seats, onQuote]);
  if (!q) return null;
  return (
    <>
      <dl className="breakdown">
        <dt>Ride fare</dt><dd>{fmtPaise(q.rideAmount)}</dd>
        <dt>Platform fee ({q.platformFeePercent}%)</dt><dd>{fmtPaise(q.platformFee)}</dd>
        <dt><b>Total</b></dt><dd><b>{fmtPaise(q.total)}</b></dd>
      </dl>
      <p className="fine">Your name and phone number will be shared with the driver once your booking is confirmed.</p>
      {q.paymentsEnabled && <p className="fine">Your seats are held for {q.seatHoldMinutes} minutes while you pay. The booking is confirmed once we verify the payment.</p>}
    </>
  );
}
