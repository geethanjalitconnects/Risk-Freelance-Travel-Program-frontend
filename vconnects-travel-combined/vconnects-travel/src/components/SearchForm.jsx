import { useState } from 'react';
import { navigate } from '../router.jsx';
import { addDays, todayStr } from '../lib/format.js';
import Icon from './Icon.jsx';
import LocationAutocomplete from './LocationAutocomplete.jsx';

// A place carried in the search URL: Google place ID + the text the user picked.
const fromQuery = (placeId, label) => (placeId ? { placeId, label: label || '', area: null } : null);

export default function SearchForm({ initial = {}, compact = false }) {
  const [from, setFrom] = useState(() => fromQuery(initial.from, initial.fromLabel));
  const [to, setTo] = useState(() => fromQuery(initial.to, initial.toLabel));
  const [date, setDate] = useState(initial.date || addDays(todayStr(), 1));
  const [seats, setSeats] = useState(Number(initial.seats) || 1);
  const [error, setError] = useState('');

  function submit(e) {
    e.preventDefault();
    if (!from || !to) return setError('Pick both places from the suggestions.');
    if (from.placeId === to.placeId) return setError('Leaving from and going to must be different places.');
    if (!date || date < todayStr()) return setError('Choose today or a later date.');
    setError('');
    navigate('/search', { from: from.placeId, fromLabel: from.label, to: to.placeId, toLabel: to.label, date, seats });
  }

  return (
    <form className={'search-form' + (compact ? ' compact' : '')} onSubmit={submit} noValidate>
      <div className="sf-fields">
        <LocationAutocomplete label="Leaving from" value={from} onChange={setFrom} placeholder="e.g. Tambaram" currentLocation />
        <button type="button" className="swap-btn" aria-label="Swap places" onClick={() => { setFrom(to); setTo(from); }}>
          <Icon name="swap" size={18} />
        </button>
        <LocationAutocomplete label="Going to" value={to} onChange={setTo} placeholder="e.g. Whitefield" />
        <label className="sf-field sf-date">
          <span>Date</span>
          <input type="date" value={date} min={todayStr()} onChange={(e) => setDate(e.target.value)} />
        </label>
        <div className="sf-field sf-seats">
          <span>Seats</span>
          <div className="stepper">
            <button type="button" onClick={() => setSeats(Math.max(1, seats - 1))} aria-label="Fewer seats">−</button>
            <output aria-live="polite">{seats}</output>
            <button type="button" onClick={() => setSeats(Math.min(4, seats + 1))} aria-label="More seats">+</button>
          </div>
        </div>
        <button type="submit" className="btn btn-accent sf-submit">Search</button>
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
    </form>
  );
}
