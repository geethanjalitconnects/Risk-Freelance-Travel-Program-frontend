import { useId, useState } from 'react';
import { navigate } from '../router.jsx';
import { ALL_CITY_NAMES } from '../data/rides.js';
import { cityByName } from '../data/cities.js';
import { addDays, todayStr } from '../lib/format.js';
import Icon from './Icon.jsx';

export default function SearchForm({ initial = {}, compact = false }) {
  const listId = useId();
  const [from, setFrom] = useState(initial.from || '');
  const [to, setTo] = useState(initial.to || '');
  const [date, setDate] = useState(initial.date || addDays(todayStr(), 1));
  const [seats, setSeats] = useState(Number(initial.seats) || 1);
  const [error, setError] = useState('');

  function submit(e) {
    e.preventDefault();
    const f = cityByName(from);
    const t = cityByName(to);
    if (!f || !t) return setError('Pick both cities from the suggestions.');
    if (f.code === t.code) return setError('Leaving from and going to must be different cities.');
    if (!date || date < todayStr()) return setError('Choose today or a later date.');
    setError('');
    navigate('/search', { from: f.name, to: t.name, date, seats });
  }

  return (
    <form className={'search-form' + (compact ? ' compact' : '')} onSubmit={submit} noValidate>
      <div className="sf-fields">
        <label className="sf-field">
          <span>Leaving from</span>
          <input list={listId} value={from} onChange={(e) => setFrom(e.target.value)} placeholder="e.g. Chennai" autoComplete="off" />
        </label>
        <button type="button" className="swap-btn" aria-label="Swap cities" onClick={() => { setFrom(to); setTo(from); }}>
          <Icon name="swap" size={18} />
        </button>
        <label className="sf-field">
          <span>Going to</span>
          <input list={listId} value={to} onChange={(e) => setTo(e.target.value)} placeholder="e.g. Bengaluru" autoComplete="off" />
        </label>
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
      <datalist id={listId}>
        {ALL_CITY_NAMES.map((n) => (
          <option key={n} value={n} />
        ))}
      </datalist>
      {error && <p className="form-error" role="alert">{error}</p>}
    </form>
  );
}
