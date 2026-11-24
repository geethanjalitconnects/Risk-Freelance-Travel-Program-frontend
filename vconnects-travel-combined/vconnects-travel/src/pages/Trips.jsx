import { useEffect, useState } from 'react';
import { Link } from '../router.jsx';
import { cityByCode } from '../data/cities.js';
import { fmtDateTime, fmtPrice, fmtTime, toIsoLocal } from '../lib/format.js';
import { useStore } from '../lib/store.js';
import { loadMe, useAuth } from '../lib/auth.js';
import {
  bookingAction, cancelRide, completeRide, getCancelQuote, getRideCancelQuote, listBookings, myRides, removeRide, travelWithLabel,
} from '../lib/ridesApi.js';
import { REFUND_STATUS, fmtPaise } from '../lib/walletApi.js';
import { payForBooking } from '../lib/checkout.js';
import { useApi } from '../lib/useApi.js';
import { fmtPlate } from '../lib/verificationApi.js';
import Icon from '../components/Icon.jsx';
import Modal from '../components/Modal.jsx';
import Avatar from '../components/Avatar.jsx';
import RiskBadge from '../components/RiskBadge.jsx';
import PassengerList from '../components/PassengerList.jsx';
import SwipeButton from '../components/SwipeButton.jsx';

const CHECKPOINTS = [
  { key: 'pickup', label: 'Picked up and seat belt on' },
  { key: 'mid', label: 'Mid-way check-in' },
  { key: 'near', label: 'Nearing destination' },
];

const HELPLINES = [
  { name: 'Emergency (all services)', num: '112' },
  { name: 'Women helpline', num: '1091' },
  { name: 'Highway / road accident help', num: '1033' },
];

const RANK = { pending_payment: -1, in_progress: 0, confirmed: 1, completed: 2, cancelled: 3, expired: 4 };
const riskObj = (b) => ({ key: b.riskBand, label: b.riskBand[0].toUpperCase() + b.riskBand.slice(1) });
const cityName = (code) => cityByCode(code)?.name || code;
const fmtMs = (ms) => fmtDateTime(toIsoLocal(new Date(ms)));

function LiveTrip({ b, contacts, act, busy }) {
  const [sos, setSos] = useState(false);
  const t = b.trip;
  const done = CHECKPOINTS.filter((c) => t.checkins[c.key]).length;
  const next = CHECKPOINTS.find((c) => !t.checkins[c.key]);
  const missed = Object.keys(t.missed || {}).length;
  const names = contacts.map((c) => c.name).join(', ');

  return (
    <div className="live">
      <div className="live-head">
        <span className="live-pill"><span className="live-dot" /> Trip in progress</span>
        <strong>{cityName(b.ride.from)} → {cityName(b.ride.to)}</strong>
      </div>
      <div className="progress" aria-label={`${done} of ${CHECKPOINTS.length} check-ins done`}>
        <span style={{ width: `${(done / CHECKPOINTS.length) * 100}%` }} />
      </div>
      <ul className="checkpoints">
        {CHECKPOINTS.map((c) => {
          const ok = t.checkins[c.key];
          const miss = t.missed?.[c.key];
          return (
            <li key={c.key} className={ok ? 'done' : miss ? 'missed' : ''}>
              <span className="cp-mark">{ok ? <Icon name="check" size={14} /> : miss ? '!' : ''}</span>
              <span className="cp-label">{c.label}</span>
              {ok && <small>{fmtTime(toIsoLocal(new Date(ok)))}</small>}
              {!ok && next?.key === c.key && (
                <button className="btn btn-sm btn-primary" disabled={busy} onClick={() => act('checkins', { key: c.key })}>I’m okay</button>
              )}
              {!ok && miss && <small className="warn-text">Missed</small>}
            </li>
          );
        })}
      </ul>
      {missed > 0 && (
        <p className="callout warn">
          {missed} missed check-in{missed > 1 ? 's' : ''}. {contacts.length ? `${names} ${contacts.length > 1 ? 'were' : 'was'} alerted.` : 'Add trusted contacts in your profile so alerts have someone to reach.'}
        </p>
      )}
      <div className="live-actions">
        <button className="btn btn-ghost" disabled={t.shared || busy} onClick={() => act('share')}>
          <Icon name="share" size={16} /> {t.shared ? 'Link shared' : 'Share live trip'}
        </button>
        {next && import.meta.env.DEV && (
          <button className="btn btn-ghost" disabled={busy} onClick={() => act('missed')} title="Development only: simulates not responding in time">
            Simulate missed check-in
          </button>
        )}
        <button className="btn btn-danger" onClick={() => { act('sos'); setSos(true); }}>
          <Icon name="alert" size={16} /> SOS
        </button>
      </div>
      {t.shared && b.shareUrl && <p className="fine">Live trip link: {b.shareUrl}</p>}
      {sos && (
        <Modal title="SOS raised" tone="danger" onClose={() => setSos(false)}>
          <p>
            {contacts.length
              ? 'We are texting your trusted contacts your trip, driver and vehicle details now.'
              : 'You have no trusted contacts to alert.'}{' '}
            If you are in danger, call for help:
          </p>
          <ul className="helplines">
            {HELPLINES.map((h) => (
              <li key={h.num}><span>{h.name}</span><a className="btn btn-danger btn-sm" href={`tel:${h.num}`}><Icon name="phone" size={14} /> {h.num}</a></li>
            ))}
          </ul>
          <h4>Your trusted contacts</h4>
          {contacts.length ? (
            <ul className="helplines">
              {contacts.map((c) => (
                <li key={c.id}><span>{c.name} <small className="muted">{c.relation}</small></span><a className="btn btn-ghost btn-sm" href={`tel:${c.phone}`}>{c.phone}</a></li>
              ))}
            </ul>
          ) : <p className="muted">None added yet. <Link to="/profile">Add contacts</Link></p>}
        </Modal>
      )}
    </div>
  );
}

function Completion({ b, run, busy }) {
  const [reporting, setReporting] = useState(false);
  const c = b.completion;
  if (!c || !['confirmed', 'in_progress'].includes(b.status)) return null;
  const started = c.canConfirm || c.passengerConfirmedAt || c.publisherConfirmedAt || c.openProblem;

  return (
    <div className="completion">
      {c.openProblem && (
        <p className="callout warn" role="status">
          {c.openProblem.party === 'passenger'
            ? <>You reported: <b>{c.openProblem.label}</b>. VConnects is reviewing it; the driver's payment is on hold until then.</>
            : <>The driver reported: <b>{c.openProblem.label}</b>. VConnects is reviewing it. If you travelled, confirm below so the reviewer sees your side.</>}
        </p>
      )}
      {started && (
        <ul className="confirm-steps" aria-label="Ride completion">
          <li className={c.passengerConfirmedAt ? 'ok' : ''}>
            <span className="cp-mark">{c.passengerConfirmedAt && <Icon name="check" size={14} />}</span>
            You {c.passengerConfirmedAt ? `confirmed · ${fmtMs(c.passengerConfirmedAt)}` : 'haven’t confirmed yet'}
          </li>
          <li className={c.publisherConfirmedAt ? 'ok' : ''}>
            <span className="cp-mark">{c.publisherConfirmedAt && <Icon name="check" size={14} />}</span>
            Driver {c.publisherConfirmedAt ? `confirmed · ${fmtMs(c.publisherConfirmedAt)}` : 'hasn’t confirmed yet'}
          </li>
        </ul>
      )}
      {c.canConfirm && (
        <SwipeButton label="Swipe to confirm ride complete" busyLabel="Confirming…" doneLabel="Confirmed" onConfirm={() => run('complete')} />
      )}
      {c.passengerConfirmedAt && !c.publisherConfirmedAt && !c.openProblem && c.autoCompleteAt && (
        <p className="fine">Waiting for the driver. If no problem is reported, the ride completes automatically on {fmtMs(c.autoCompleteAt)}.</p>
      )}
      {c.reportKinds.length > 0 && (
        <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => setReporting(true)}>
          <Icon name="alert" size={14} /> Report a problem
        </button>
      )}
      {reporting && <ReportProblem kinds={c.reportKinds} run={run} onClose={() => setReporting(false)} />}
    </div>
  );
}

function ReportProblem({ kinds, run, onClose }) {
  const [kind, setKind] = useState(kinds[0].value);
  const [details, setDetails] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    if (busy) return;
    if (details.trim().length < 10) return setErr('Tell us what happened (at least a few words).');
    setBusy(true);
    setErr('');
    try {
      await run('problems', { kind, details: details.trim() });
      onClose();
    } catch (e2) {
      setErr(e2.message);
      setBusy(false);
    }
  }

  return (
    <Modal title="Report a problem" onClose={onClose}>
      <form className="form-stack" onSubmit={submit} noValidate>
        <fieldset className="field">
          <legend>What happened?</legend>
          {kinds.map((k) => (
            <label key={k.value} className="check">
              <input type="radio" name="kind" value={k.value} checked={kind === k.value} onChange={() => setKind(k.value)} /> {k.label}
            </label>
          ))}
        </fieldset>
        <label className="field"><span>Details</span>
          <textarea rows={4} maxLength={2000} value={details} onChange={(e) => setDetails(e.target.value)} placeholder="When and where, and what you saw." />
        </label>
        <p className="fine">The ride won't complete and the driver won't be paid until VConnects reviews your report. In an emergency, call 112.</p>
        {err && <p className="form-error" role="alert">{err}</p>}
        <div className="live-actions">
          <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Sending…' : 'Send report'}</button>
          <button className="btn btn-ghost" type="button" onClick={onClose} disabled={busy}>Cancel</button>
        </div>
      </form>
    </Modal>
  );
}

function CancelBooking({ b, run, onClose }) {
  const [quote, setQuote] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getCancelQuote(b.id).then(setQuote).catch((e) => setErr(e.message));
  }, [b.id]);

  async function confirm() {
    if (busy) return;
    setBusy(true);
    setErr('');
    try {
      await run('cancel');
      onClose();
    } catch (e) {
      setErr(e.message);
      setBusy(false);
    }
  }

  return (
    <Modal title="Cancel this booking?" onClose={onClose}>
      <div className="form-stack">
        {!quote && !err && <p className="muted">Working out your refund…</p>}
        {quote && (
          <>
            {quote.paid && (
              <dl className="breakdown">
                <dt>You paid</dt><dd>{fmtPaise(quote.totalPaid)}</dd>
                <dt>Cancellation fee</dt><dd>−{fmtPaise(quote.fee)}</dd>
                <dt>Refund to your original payment method</dt><dd><b>{fmtPaise(quote.refund)}</b></dd>
              </dl>
            )}
            <p>{quote.message}</p>
            <p className="fine">More than 24 hours before departure, 15% of what you paid is kept; within 24 hours, 10% is kept. Refunds usually take 5 to 7 working days.</p>
          </>
        )}
        {err && <p className="form-error" role="alert">{err}</p>}
        <div className="live-actions">
          <button className="btn btn-danger" onClick={confirm} disabled={busy || !quote}>{busy ? 'Cancelling…' : 'Cancel booking'}</button>
          <button className="btn btn-ghost" onClick={onClose} disabled={busy}>Keep booking</button>
        </div>
      </div>
    </Modal>
  );
}

function CancelSummary({ c }) {
  const byText = { passenger: 'You cancelled', publisher: 'The driver cancelled', admin: 'VConnects cancelled', system: 'Cancelled' }[c.by] || 'Cancelled';
  return (
    <p className="callout cancel-summary">
      {byText} this booking{c.reason && c.by !== 'passenger' ? `: ${c.reason}` : '.'}{' '}
      {c.refundStatus
        ? <>Refund <b>{fmtPaise(c.refund)}</b> to your original payment method ({REFUND_STATUS[c.refundStatus] || c.refundStatus}){c.fee > 0 && <>; cancellation fee {fmtPaise(c.fee)}</>}.</>
        : 'Nothing was paid, so there is nothing to refund.'}
    </p>
  );
}

function Rate({ b, act, busy }) {
  if (b.rating) return <p className="muted">You rated this driver {b.rating}/5. Thank you.</p>;
  return (
    <div className="rate">
      <span>Rate {b.ride.driver.name}:</span>
      {[1, 2, 3, 4, 5].map((n) => (
        <button key={n} className="star-btn" disabled={busy} aria-label={`${n} star${n > 1 ? 's' : ''}`} onClick={() => act('rate', { stars: n })}>
          <Icon name="star" size={22} />
        </button>
      ))}
    </div>
  );
}

function BookingCard({ b, contacts, onChange }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [cancelling, setCancelling] = useState(false);
  const live = b.status === 'in_progress';

  // Throws on failure (for the swipe and the report form, which show their own errors).
  async function run(action, body) {
    setBusy(true);
    setErr('');
    try {
      onChange(await bookingAction(b.id, action, body));
      if (['start', 'complete', 'cancel'].includes(action)) loadMe(); // header's live-trip dot
    } finally {
      setBusy(false);
    }
  }

  async function pay() {
    setBusy(true);
    setErr('');
    try {
      onChange(await payForBooking(b.id));
    } catch (e) {
      setErr(e.dismissed ? 'Payment not completed. You can try again while your seats are held.' : e.message);
    } finally {
      setBusy(false);
    }
  }

  async function act(action, body) {
    try {
      await run(action, body);
    } catch (e) {
      setErr(e.message);
    }
  }

  return (
    <article className={'trip-card status-' + b.status}>
      <div className="trip-top">
        <div>
          <h3>{cityName(b.ride.from)} → {cityName(b.ride.to)}</h3>
          <p className="muted">{fmtDateTime(b.ride.depart)} · {b.seats} seat{b.seats > 1 ? 's' : ''} · {fmtPrice(b.total)}</p>
        </div>
        <span className={'status-tag st-' + b.status}>{b.status.replace('_', ' ')}</span>
      </div>
      <div className="trip-mid">
        <Avatar name={b.ride.driver.name} size={36} />
        <span>{b.ride.driver.name} · {b.ride.vehicle.model}{b.ride.vehicle.number && ` · ${fmtPlate(b.ride.vehicle.number)}`}</span>
        <RiskBadge band={riskObj(b)} score={b.riskScore} />
      </div>
      {live && <LiveTrip b={b} contacts={contacts} act={act} busy={busy} />}
      <Completion b={b} run={run} busy={busy} />
      {b.status === 'confirmed' && (
        <div className="live-actions">
          <button className="btn btn-primary" disabled={busy} onClick={() => act('start')}>Start trip</button>
          <Link to={`/ride/${encodeURIComponent(b.rideId)}`} className="btn btn-ghost">View ride</Link>
          <button className="btn btn-ghost" disabled={busy} onClick={() => setCancelling(true)}>Cancel</button>
        </div>
      )}
      {b.status === 'pending_payment' && (
        <div className="live-actions">
          <button className="btn btn-accent" disabled={busy} onClick={pay}>Pay {b.amounts && fmtPaise(b.amounts.total)}</button>
          <button className="btn btn-ghost" disabled={busy} onClick={() => setCancelling(true)}>Cancel</button>
          {b.holdExpiresAt && <span className="fine">Seats held until {fmtTime(toIsoLocal(new Date(b.holdExpiresAt)))}</span>}
        </div>
      )}
      {b.status === 'expired' && <p className="fine">Not paid in time, so the seats were released.</p>}
      {cancelling && <CancelBooking b={b} run={run} onClose={() => setCancelling(false)} />}
      {b.cancellation && <CancelSummary c={b.cancellation} />}
      {b.status === 'completed' && <Rate b={b} act={act} busy={busy} />}
      {err && <p className="form-error" role="alert">{err}</p>}
      {b.events?.length > 0 && (
        <details className="log">
          <summary>Trip log ({b.events.length})</summary>
          <ol>
            {[...b.events].reverse().map((e, i) => (
              <li key={i}><time>{new Date(e.t).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}</time> {e.text}</li>
            ))}
          </ol>
        </details>
      )}
    </article>
  );
}

function RideComplete({ r, onUpdated }) {
  const c = r.completion;
  const waiting = (r.passengers || []).filter(
    (p) => ['confirmed', 'in_progress'].includes(p.status) && !p.youConfirmed && p.openProblem !== 'passenger_no_show',
  );
  const [noShow, setNoShow] = useState([]);
  const [note, setNote] = useState('');
  const toggle = (id) => setNoShow((list) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]));
  const fromTime = fmtTime(c.noShowFrom);

  return (
    <div className="completion ride-complete">
      <h4>Complete this ride</h4>
      <p className="muted">Confirm the passengers who travelled with you. Mark anyone who didn’t turn up.</p>
      <ul className="contacts">
        {waiting.map((p) => (
          <li key={p.bookingId}>
            <span>
              <b>{p.name}</b> <span className="muted">· {p.seats} seat{p.seats > 1 ? 's' : ''}</span>
              {p.passengerConfirmed && <span className="chip chip-ok" style={{ marginLeft: 6 }}>Confirmed by passenger</span>}
            </span>
            <label className="check" title={c.noShowOpen ? undefined : `You can report a no-show from ${fromTime}`}>
              <input type="checkbox" checked={noShow.includes(p.bookingId)} disabled={!c.noShowOpen} onChange={() => toggle(p.bookingId)} />
              Didn’t show up
            </label>
          </li>
        ))}
      </ul>
      {!c.noShowOpen && <p className="fine">No-shows can be reported from {fromTime}, 30 minutes after departure.</p>}
      {noShow.length > 0 && (
        <label className="field"><span>What happened? (helps our review)</span>
          <textarea rows={2} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Waited 15 minutes at the pickup, called twice." />
        </label>
      )}
      <SwipeButton
        key={noShow.join(',')}
        label={noShow.length ? `Swipe to complete (${noShow.length} no-show)` : 'Swipe to complete ride'}
        busyLabel="Completing…"
        doneLabel="Ride confirmed"
        onConfirm={async () => onUpdated(await completeRide(r.id, { noShow, note }))}
      />
      <p className="fine">Your earning for each passenger is released once they confirm too, or automatically 24 hours after arrival if no problem is reported. No-shows are reviewed by VConnects.</p>
    </div>
  );
}

function CancelRide({ r, onClose, onCancelled }) {
  const [quote, setQuote] = useState(null);
  const [reason, setReason] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getRideCancelQuote(r.id).then(setQuote).catch((e) => setErr(e.message));
  }, [r.id]);

  async function confirm(e) {
    e.preventDefault();
    if (busy) return;
    if (reason.trim().length < 5) return setErr('Tell your passengers why you’re cancelling.');
    setBusy(true);
    setErr('');
    try {
      await cancelRide(r.id, reason.trim());
      onCancelled(r.id);
    } catch (e2) {
      setErr(e2.message);
      setBusy(false);
    }
  }

  return (
    <Modal title="Cancel this ride?" onClose={onClose}>
      <form className="form-stack" onSubmit={confirm} noValidate>
        {!quote && !err && <p className="muted">Checking your bookings…</p>}
        {quote && (
          <>
            <dl className="breakdown">
              <dt>Passengers refunded in full</dt><dd>{quote.passengers}</dd>
              {quote.paidPassengers > 0 && <><dt>Total refunded</dt><dd>{fmtPaise(quote.refundTotal)}</dd></>}
              <dt>Your penalty</dt><dd><b>{fmtPaise(quote.penalty)}</b></dd>
            </dl>
            <p className={quote.penalty ? 'callout warn' : ''}>{quote.message}</p>
          </>
        )}
        <label className="field"><span>Reason (your passengers see this)</span>
          <textarea rows={3} maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="My car broke down." />
        </label>
        {err && <p className="form-error" role="alert">{err}</p>}
        <div className="live-actions">
          <button className="btn btn-danger" type="submit" disabled={busy || !quote}>{busy ? 'Cancelling…' : 'Cancel ride'}</button>
          <button className="btn btn-ghost" type="button" onClick={onClose} disabled={busy}>Keep ride</button>
        </div>
      </form>
    </Modal>
  );
}

function PublishedCard({ r, onRemoved, onUpdated }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const booked = r.seatsTotal - r.seatsLeft;
  const departed = r.depart <= toIsoLocal(new Date());
  const [cancelling, setCancelling] = useState(false);
  const started = (r.passengers || []).some((p) => p.status === 'in_progress');

  async function remove() {
    if (!window.confirm('Remove this ride?')) return;
    setBusy(true);
    setErr('');
    try {
      await removeRide(r.id);
      onRemoved(r.id);
    } catch (e) {
      setErr(e.message);
      setBusy(false);
    }
  }

  return (
    <article className="trip-card">
      <div className="trip-top">
        <div>
          <h3>{cityName(r.from)} → {cityName(r.to)}</h3>
          <p className="muted">
            {fmtDateTime(r.depart)} · {booked}/{r.seatsTotal} seats booked · {fmtPrice(r.price)}/seat · {r.vehicle.model}
            {r.travelWith !== 'anyone' && ` · ${travelWithLabel(r.travelWith)}`}
          </p>
        </div>
        <span className="status-tag st-confirmed">{departed ? 'departed' : 'published'}</span>
      </div>
      <div className="live-actions">
        <Link to={`/ride/${encodeURIComponent(r.id)}`} className="btn btn-ghost">View as passenger</Link>
        {!departed && <Link to={`/edit/${encodeURIComponent(r.id)}`} className="btn btn-ghost">Edit</Link>}
        {r.hasBookings ? (
          !departed && !started && (
            <button className="btn btn-ghost" disabled={busy} onClick={() => setCancelling(true)}>
              <Icon name="close" size={16} /> Cancel ride
            </button>
          )
        ) : (
          <button className="btn btn-ghost" disabled={busy} onClick={remove}>
            <Icon name="trash" size={16} /> Remove
          </button>
        )}
      </div>
      <h4>Passengers</h4>
      <PassengerList passengers={r.passengers} />
      {r.completion?.canComplete && <RideComplete r={r} onUpdated={onUpdated} />}
      {r.listed === false && (
        <p className="callout warn">Hidden from search until your <Link to="/verification">driver verification</Link> is approved. Passengers who already booked still see it.</p>
      )}
      {r.hasBookings && !departed && (
        <p className="fine">This ride has bookings. If you cancel it, every passenger is refunded in full; within 24 hours of departure a penalty of 10% of the fare is deducted from your earnings.</p>
      )}
      {cancelling && <CancelRide r={r} onClose={() => setCancelling(false)} onCancelled={(id) => { setCancelling(false); onRemoved(id); }} />}
      {err && <p className="form-error" role="alert">{err}</p>}
    </article>
  );
}

export default function Trips() {
  const auth = useAuth();
  if (auth.status === 'loading') return <div className="container page"><p className="muted">Loading your trips…</p></div>;
  if (auth.status !== 'signed-in') {
    return (
      <div className="container page narrow">
        <h1 className="page-title">My trips</h1>
        <div className="panel form-stack">
          <p>Sign in to see your bookings and the rides you published.</p>
          <Link to="/login?next=/trips" className="btn btn-accent">Sign in or sign up</Link>
        </div>
      </div>
    );
  }
  return <TripsList userId={auth.user.id} />;
}

function TripsList({ userId }) {
  const contacts = useStore((s) => s.profile.contacts);
  const bookings = useApi(listBookings, [userId]);
  const published = useApi(myRides, [userId]);

  const sorted = [...(bookings.data || [])].sort((a, b) => RANK[a.status] - RANK[b.status] || b.createdAt - a.createdAt);
  const replace = (nb) => bookings.setData((list) => list.map((x) => (x.id === nb.id ? nb : x)));

  return (
    <div className="container page">
      <h1 className="page-title">My trips</h1>
      {contacts.length === 0 && (
        <p className="callout">Add at least one trusted contact so check-ins and SOS work as intended. <Link to="/profile">Open profile</Link></p>
      )}
      <h2 className="sub">Booked rides</h2>
      {bookings.error ? (
        <p className="callout warn">{bookings.error.message} <button className="btn btn-ghost btn-sm" onClick={bookings.reload}>Try again</button></p>
      ) : bookings.loading && !bookings.data ? (
        <p className="muted">Loading bookings…</p>
      ) : sorted.length === 0 ? (
        <div className="empty"><h3>No bookings yet</h3><p>Find a ride and book a seat to start a protected trip.</p><Link to="/" className="btn btn-primary">Find a ride</Link></div>
      ) : (
        <div className="trip-list">{sorted.map((b) => <BookingCard key={b.id} b={b} contacts={contacts} onChange={replace} />)}</div>
      )}

      <div className="results-head">
        <h2 className="sub">Rides you published</h2>
        <button className="btn btn-ghost btn-sm" onClick={() => { published.reload(); bookings.reload(); }}>Refresh</button>
      </div>
      {published.error ? (
        <p className="callout warn">{published.error.message} <button className="btn btn-ghost btn-sm" onClick={published.reload}>Try again</button></p>
      ) : published.loading && !published.data ? (
        <p className="muted">Loading rides…</p>
      ) : (published.data || []).length === 0 ? (
        <p className="muted">Nothing published yet. <Link to="/publish">Publish a ride</Link></p>
      ) : (
        <div className="trip-list">
          {published.data.map((r) => (
            <PublishedCard
              key={r.id}
              r={r}
              onRemoved={(id) => published.setData((list) => list.filter((x) => x.id !== id))}
              onUpdated={(nr) => { published.setData((list) => list.map((x) => (x.id === nr.id ? nr : x))); bookings.reload(); }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
