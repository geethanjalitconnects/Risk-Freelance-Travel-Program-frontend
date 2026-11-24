import { useEffect, useState } from 'react';
import { Link, navigate } from '../router.jsx';
import { VEHICLES } from '../data/rides.js';
import { VEHICLE_FEATURES } from '../lib/risk.js';
import { addDays, fmtPrice, todayStr, toIsoLocal } from '../lib/format.js';
import { useStore } from '../lib/store.js';
import { useAuth } from '../lib/auth.js';
import { useApi } from '../lib/useApi.js';
import { TRAVEL_WITH, getRide, previewRide, publishRide, updateRide } from '../lib/ridesApi.js';
import { getVerification } from '../lib/verificationApi.js';
import RiskBreakdown from '../components/RiskBreakdown.jsx';
import LocationAutocomplete from '../components/LocationAutocomplete.jsx';
import { getArea } from '../lib/placesApi.js';

const blankForm = () => ({
  from: null, to: null, date: addDays(todayStr(), 1), time: '07:00', seats: 3, price: '',
  model: '', year: String(new Date().getFullYear() - 2), features: ['airbags', 'abs'],
  travelWith: 'anyone', notes: '', pickup: '', dropoff: '',
});

// A stored ride's place, in the shape LocationAutocomplete uses.
const placeOf = (area, placeId) => ({ label: area.name, placeId, area, stored: true });

function formFromRide(r) {
  return {
    from: placeOf(r.fromArea, r.fromPlaceId), to: placeOf(r.toArea, r.toPlaceId),
    date: r.date, time: r.depart.slice(11, 16), seats: r.seatsTotal,
    price: String(r.price), model: r.vehicle.model, year: String(r.vehicle.year), features: r.vehicle.features,
    travelWith: r.travelWith, notes: r.notes, pickup: r.pickup, dropoff: r.dropoff,
  };
}

// Pickup / drop-off options: the picked place itself, then the area's meeting points (admin-managed),
// plus the ride's current choice when editing. A blank value means the first option.
function pointOptions(place, current) {
  if (!place) return [];
  const opts = [...(place.stored ? [] : [place.label]), ...(place.area?.meetingPoints || [])];
  if (current && !opts.includes(current)) opts.unshift(current);
  return [...new Set(opts.filter(Boolean))];
}

// API field -> form field, for server-side validation messages.
const FIELD_MAP = { from: 'from', to: 'to', depart: 'time', price: 'price', seatsTotal: 'seats', pickup: 'pickup', dropoff: 'dropoff', travelWith: 'travelWith', notes: 'notes' };
const first = (v) => (Array.isArray(v) ? v[0] : v);

function serverErrors(data) {
  const err = {};
  for (const [k, v] of Object.entries(data || {})) {
    if (k === 'vehicle') {
      if (v && typeof v === 'object' && !Array.isArray(v)) {
        if (v.model) err.model = first(v.model);
        if (v.year) err.year = first(v.year);
      } else err.model = first(v);
    } else if (FIELD_MAP[k]) err[FIELD_MAP[k]] = first(v);
    else if (k !== 'code') err.form = first(v);
  }
  return err;
}

export default function Publish({ editId }) {
  const auth = useAuth();
  if (auth.status === 'loading') return <div className="container page"><p className="muted">Loading…</p></div>;
  if (auth.status !== 'signed-in') {
    const next = editId ? `/edit/${editId}` : '/publish';
    return (
      <div className="container page narrow">
        <h1 className="page-title">{editId ? 'Edit ride' : 'Publish a ride'}</h1>
        <div className="panel form-stack">
          <p>Sign in to offer seats on a trip you are already making.</p>
          <Link to={`/login?next=${encodeURIComponent(next)}`} className="btn btn-accent">Sign in or sign up</Link>
        </div>
      </div>
    );
  }
  return <VerificationGate userId={auth.user.id} editId={editId} />;
}

// Only approved drivers can publish or edit rides (the server enforces this too).
function VerificationGate({ userId, editId }) {
  const { data: v, error, loading, reload } = useApi(getVerification, [userId]);
  if (loading && !v) return <div className="container page"><p className="muted">Checking your driver verification…</p></div>;
  if (error) {
    return (
      <div className="container page narrow">
        <p className="callout warn">{error.message}</p>
        <button className="btn btn-primary" onClick={reload}>Try again</button>
      </div>
    );
  }
  if (!v.canPublish) return <NotVerified v={v} editing={Boolean(editId)} />;
  return <PublishForm editId={editId} />;
}

function NotVerified({ v, editing }) {
  const title = {
    not_submitted: 'Verify yourself to publish rides',
    pending: 'Your documents are under review',
    rejected: 'Your verification was rejected',
    resubmit_requested: 'Please re-upload some documents',
    revoked: 'Your verification was revoked',
  }[v.status];
  const action = { not_submitted: 'Submit documents', pending: 'View status', rejected: 'Fix and resubmit', resubmit_requested: 'Re-upload documents', revoked: 'Resubmit documents' }[v.status];
  return (
    <div className="container page narrow">
      <h1 className="page-title">{editing ? 'Edit ride' : 'Publish a ride'}</h1>
      <div className="panel form-stack">
        <h3>{title}</h3>
        <p className={['rejected', 'revoked', 'resubmit_requested'].includes(v.status) ? 'callout warn pre-line' : 'muted'}>{v.blockMessage}</p>
        {v.status === 'not_submitted' && (
          <p className="muted">You need your vehicle registration number, both sides of your driving licence and one government ID
            (masked Aadhaar, PAN, Voter ID or passport). Our team usually reviews documents within a day.</p>
        )}
        <Link to="/verification" className="btn btn-accent">{action}</Link>
      </div>
    </div>
  );
}

function PublishForm({ editId }) {
  const profile = useStore((s) => s.profile);
  const [f, setF] = useState(blankForm);
  const [ride, setRide] = useState(null); // the ride being edited
  const [loadErr, setLoadErr] = useState('');
  const [loading, setLoading] = useState(Boolean(editId));
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(null); // {km, minFare, maxFare, risk}
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));
  const toggleFeature = (k) => set('features', f.features.includes(k) ? f.features.filter((x) => x !== k) : [...f.features, k]);

  useEffect(() => {
    if (!editId) return undefined;
    let alive = true;
    getRide(editId)
      .then((r) => {
        if (!alive) return;
        if (!r.isOwn) setLoadErr('You can only edit rides you published.');
        else if (r.depart <= toIsoLocal(new Date())) setLoadErr('This ride has already left, so it can no longer be edited.');
        else {
          setRide(r);
          setF(formFromRide(r));
        }
      })
      .catch((e) => alive && setLoadErr(e.status === 404 ? 'Ride not found. It may have been removed.' : e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [editId]);

  // Once passengers have booked, the terms they booked on are locked (the server enforces this too).
  const locked = Boolean(ride?.hasBookings);
  const booked = ride ? ride.seatsTotal - ride.seatsLeft : 0;

  const from = f.from;
  const to = f.to;
  const sameArea = Boolean(from?.area && to?.area && from.area.code === to.area.code);
  const routeOk = Boolean(from && to && !sameArea);
  const routeChanged = !ride || from?.placeId !== ride.fromPlaceId || to?.placeId !== ride.toPlaceId
    || (from && !from.stored) || (to && !to.stored);

  // A stored ride's areas come without meeting points: load them once for the dropdowns.
  useEffect(() => {
    for (const key of ['from', 'to']) {
      const p = f[key];
      if (p?.stored && p.area && !p.area.meetingPoints) {
        getArea(p.area.code)
          .then((area) => setF((prev) => (prev[key] === p ? { ...prev, [key]: { ...p, area } } : prev)))
          .catch(() => {});
      }
    }
  }, [f.from, f.to]); // eslint-disable-line react-hooks/exhaustive-deps

  const pickPlace = (key, pointKey) => (v) => setF((p) => ({ ...p, [key]: v, [pointKey]: '' }));
  const pickupOptions = pointOptions(from, ride && !routeChanged ? ride.pickup : '');
  const dropoffOptions = pointOptions(to, ride && !routeChanged ? ride.dropoff : '');

  // Risk score and the allowed fare range come from the server, which holds the road distances
  // and the admin's fare settings. Debounced so typing doesn't fire a request per keystroke.
  const featuresKey = f.features.join(',');
  useEffect(() => {
    if (!routeOk || !f.date || !f.time) {
      setPreview(null);
      return undefined;
    }
    let alive = true;
    const t = setTimeout(() => {
      const year = Number(f.year);
      previewRide({
        from: from.placeId, to: to.placeId, depart: `${f.date}T${f.time}`,
        vehicle: { model: f.model, features: f.features, ...(year >= 1900 && year <= 2100 ? { year } : {}) },
      })
        .then((p) => alive && setPreview(p))
        .catch(() => alive && setPreview(null));
    }, 350);
    return () => {
      alive = false;
      clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeOk, from?.placeId, to?.placeId, f.date, f.time, f.model, f.year, featuresKey]);

  const travelOption = TRAVEL_WITH.find((t) => t.value === f.travelWith);

  async function submit(e) {
    e.preventDefault();
    const err = {};
    if (!locked) {
      if (!from) err.from = 'Pick a place from the suggestions.';
      if (!to) err.to = 'Pick a place from the suggestions.';
      if (sameArea) err.to = 'Pick a destination in a different area from the start.';
      if (!f.date || f.date < todayStr()) err.date = 'Pick today or a later date.';
      if (f.date && f.time && new Date(`${f.date}T${f.time}`) <= new Date()) err.time = 'That time has already passed.';
      const price = Number(f.price);
      if (!price) err.price = 'Enter a price per seat.';
      else if (preview && price < preview.minFare) err.price = `The fare must be at least ${fmtPrice(preview.minFare)} per seat for this route.`;
      else if (preview && price > preview.maxFare) err.price = `The fare can be at most ${fmtPrice(preview.maxFare)} per seat for this route.`;
      if (!f.model.trim()) err.model = 'Tell passengers what you drive.';
      const yr = Number(f.year);
      if (!yr || yr < 1995 || yr > new Date().getFullYear() + 1) err.year = 'Enter a valid year.';
      if (travelOption?.gender && profile.gender !== travelOption.gender) err.travelWith = travelOption.hint;
    }
    if (Number(f.seats) < booked) err.seats = `${booked} seat${booked === 1 ? ' is' : 's are'} already booked.`;
    setErrors(err);
    if (Object.keys(err).length) return;

    const body = { seatsTotal: Number(f.seats), pickup: f.pickup, dropoff: f.dropoff, notes: f.notes.trim() };
    if (!locked) {
      if (routeChanged) Object.assign(body, { from: from.placeId, to: to.placeId, fromLabel: from.label, toLabel: to.label });
      Object.assign(body, {
        depart: `${f.date}T${f.time}`,
        price: Number(f.price),
        travelWith: f.travelWith,
        vehicle: { model: f.model.trim(), year: Number(f.year), features: f.features },
      });
    }

    setBusy(true);
    try {
      if (ride) await updateRide(ride.id, body);
      else await publishRide(body);
      navigate('/trips');
    } catch (ex) {
      if (ex.status === 403 && String(ex.data?.code || '').startsWith('verification_')) {
        setErrors({ form: ex.message, verification: true });
      } else {
        const mapped = serverErrors(ex.data);
        setErrors(Object.keys(mapped).length ? mapped : { form: ex.message });
      }
    } finally {
      setBusy(false);
    }
  }

  const Err = ({ k }) => (errors[k] ? <small className="field-error" role="alert">{errors[k]}</small> : null);

  if (loading) return <div className="container page"><p className="muted">Loading ride…</p></div>;
  if (loadErr) {
    return (
      <div className="container page empty">
        <h2>Can’t edit this ride</h2>
        <p>{loadErr}</p>
        <Link to="/trips" className="btn btn-primary">Back to My trips</Link>
      </div>
    );
  }

  const priceHint = locked
    ? 'The fare is locked because passengers have booked.'
    : preview
    ? `Allowed for ${preview.km} km: ${fmtPrice(preview.minFare)} to ${fmtPrice(preview.maxFare)} per seat`
    : 'Choose the route, date and time to see the allowed fare.';

  return (
    <div className="container page">
      <h1 className="page-title">{ride ? 'Edit ride' : 'Publish a ride'}</h1>
      <p className="muted lead">
        {ride
          ? 'Update the details passengers see for this ride.'
          : 'Offer empty seats on a trip you are already making. Passengers see a live risk score and your Verified badge.'}
      </p>
      {locked && (
        <p className="callout warn">
          Passengers have booked {booked} seat{booked === 1 ? '' : 's'} on this ride, so the route, time, fare, vehicle and who can travel with you are locked.
          You can still change seats, meeting points and the note.
        </p>
      )}
      <form className="publish-grid" onSubmit={submit} noValidate>
        <div className="panel form-stack">
          <h3>Trip</h3>
          <div className="row2">
            <div>
              <LocationAutocomplete label="Leaving from" className="field" value={f.from} onChange={pickPlace('from', 'pickup')}
                placeholder="Area, town or city" disabled={locked} invalid={Boolean(errors.from)} currentLocation />
              <Err k="from" />
            </div>
            <div>
              <LocationAutocomplete label="Going to" className="field" value={f.to} onChange={pickPlace('to', 'dropoff')}
                placeholder="Area, town or city" disabled={locked} invalid={Boolean(errors.to)} />
              <Err k="to" />
            </div>
          </div>
          <div className="row2">
            <label className="field"><span>Date</span>
              <input type="date" min={todayStr()} value={f.date} onChange={(e) => set('date', e.target.value)} disabled={locked} /><Err k="date" /></label>
            <label className="field"><span>Departure time</span>
              <input type="time" value={f.time} onChange={(e) => set('time', e.target.value)} disabled={locked} /><Err k="time" /></label>
          </div>
          <div className="row2">
            <label className="field"><span>Pickup point (optional)</span>
              <select value={f.pickup} onChange={(e) => set('pickup', e.target.value)} disabled={!from}>
                <option value="">{pickupOptions[0] || (from ? from.area?.name : 'Choose a place first')}</option>
                {pickupOptions.slice(1).map((p) => <option key={p}>{p}</option>)}
              </select><Err k="pickup" /></label>
            <label className="field"><span>Drop-off point (optional)</span>
              <select value={f.dropoff} onChange={(e) => set('dropoff', e.target.value)} disabled={!to}>
                <option value="">{dropoffOptions[0] || (to ? to.area?.name : 'Choose a place first')}</option>
                {dropoffOptions.slice(1).map((p) => <option key={p}>{p}</option>)}
              </select><Err k="dropoff" /></label>
          </div>
          <div className="row2">
            <label className="field"><span>Seats offered</span>
              <select value={f.seats} onChange={(e) => set('seats', e.target.value)}>
                {[1, 2, 3, 4].map((n) => <option key={n} value={n} disabled={n < booked}>{n}</option>)}
              </select><Err k="seats" /></label>
            <label className="field"><span>Price per seat (₹)</span>
              <input
                type="number"
                step="10"
                min={preview?.minFare}
                max={preview?.maxFare}
                value={f.price}
                onChange={(e) => set('price', e.target.value)}
                placeholder={preview ? String(preview.minFare) : 'e.g. 5600'}
                disabled={locked}
              />
              <small className="hint">{priceHint}</small>
              {!locked && preview && !f.price && (
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => set('price', String(preview.minFare))}>Use the minimum ({fmtPrice(preview.minFare)})</button>
              )}
              <Err k="price" /></label>
          </div>
          <label className="field"><span>Who can travel with me</span>
            <select value={f.travelWith} onChange={(e) => set('travelWith', e.target.value)} disabled={locked}>
              {TRAVEL_WITH.map((t) => (
                <option key={t.value} value={t.value} disabled={Boolean(t.gender) && profile.gender !== t.gender}>
                  {t.label}{t.gender && profile.gender !== t.gender ? ` (${t.gender === 'F' ? 'female' : 'male'} drivers)` : ''}
                </option>
              ))}
            </select>
            {!locked && !profile.gender && <small className="hint">Set your gender in your <Link to="/profile">profile</Link> to offer a women-only or men-only ride.</small>}
            <Err k="travelWith" /></label>

          <h3>Vehicle</h3>
          <div className="row2">
            <label className="field"><span>Make and model</span>
              <input list="vmodels" value={f.model} onChange={(e) => set('model', e.target.value)} placeholder="e.g. Hyundai Creta" disabled={locked} />
              <datalist id="vmodels">{VEHICLES.map((v) => <option key={v.model} value={v.model} />)}</datalist>
              <Err k="model" /></label>
            <label className="field"><span>Year</span>
              <input type="number" value={f.year} onChange={(e) => set('year', e.target.value)} disabled={locked} /><Err k="year" /></label>
          </div>
          <p className="fine">The registration number is the one on your <Link to="/verification">driver verification</Link>; passengers see it once they book.</p>
          <fieldset className="field" disabled={locked}>
            <legend>Safety features</legend>
            <div className="chips-select">
              {Object.entries(VEHICLE_FEATURES).map(([k, label]) => (
                <label key={k} className={'toggle' + (f.features.includes(k) ? ' on' : '')}>
                  <input type="checkbox" checked={f.features.includes(k)} onChange={() => toggleFeature(k)} /> {label}
                </label>
              ))}
            </div>
          </fieldset>
          <label className="field"><span>Note for passengers (optional)</span>
            <textarea rows="2" maxLength="140" value={f.notes} onChange={(e) => set('notes', e.target.value)} placeholder="Stops, luggage, music…" /><Err k="notes" /></label>
          {errors.form && (
            <p className="form-error" role="alert">
              {errors.form} {errors.verification && <Link to="/verification">Open driver verification</Link>}
            </p>
          )}
          <div className="row2">
            <button type="submit" className="btn btn-accent" disabled={busy}>{busy ? 'Saving…' : ride ? 'Save changes' : 'Publish ride'}</button>
            {ride && <Link to="/trips" className="btn btn-ghost">Cancel</Link>}
          </div>
        </div>

        <aside className="panel sticky">
          <h3>Risk preview</h3>
          {preview ? <RiskBreakdown risk={preview.risk} compact /> : <p className="muted">Choose two cities, a date and a time to preview how passengers will see your trip’s risk score.</p>}
        </aside>
      </form>
    </div>
  );
}
