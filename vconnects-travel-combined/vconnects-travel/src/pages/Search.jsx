import { useMemo, useState } from 'react';
import SearchForm from '../components/SearchForm.jsx';
import RideCard from '../components/RideCard.jsx';
import { fmtDate } from '../lib/format.js';
import { searchRides } from '../lib/ridesApi.js';
import { useApi } from '../lib/useApi.js';

const SORTS = {
  earliest: { label: 'Earliest', fn: (a, b) => a.depart.localeCompare(b.depart) },
  cheapest: { label: 'Cheapest', fn: (a, b) => a.price - b.price },
  safest: { label: 'Safest', fn: (a, b) => a.risk.score - b.risk.score },
};

export default function Search({ query }) {
  const [sort, setSort] = useState('safest');
  const [travelWith, setTravelWith] = useState('any');
  const [maxRisk, setMaxRisk] = useState('any');
  const [daylight, setDaylight] = useState(false);

  const seats = Number(query.seats) || 1;
  // from / to are Google place IDs picked in the search form; the labels are only for display.
  const valid = Boolean(query.from && query.to && query.date);

  const { data, error, loading, reload } = useApi(
    () => (valid ? searchRides({ from: query.from, to: query.to, date: query.date, seats }) : Promise.resolve([])),
    [valid, query.from, query.to, query.date, seats]
  );
  const rides = data || [];

  const shown = useMemo(() => {
    let list = rides;
    if (travelWith !== 'any') list = list.filter((r) => r.travelWith === travelWith);
    if (daylight) list = list.filter((r) => { const h = Number(r.depart.slice(11, 13)); return h >= 6 && h < 17; });
    if (maxRisk !== 'any') list = list.filter((r) => r.risk.score < Number(maxRisk));
    return [...list].sort(SORTS[sort].fn);
  }, [rides, sort, travelWith, maxRisk, daylight]);

  return (
    <div className="container page">
      <SearchForm key={JSON.stringify(query)} initial={query} compact />
      {!valid ? (
        <div className="empty">
          <h2>Where to?</h2>
          <p>Pick where you're leaving from, where you're going and a date to see rides nearby.</p>
        </div>
      ) : (
        <div className="results-layout">
          <aside className="filters" aria-label="Filters">
            <h3>Filters</h3>
            <label className="check"><input type="checkbox" checked={daylight} onChange={(e) => setDaylight(e.target.checked)} /> Daytime departures (6 am - 5 pm)</label>
            <label className="field">
              <span>Who can travel</span>
              <select value={travelWith} onChange={(e) => setTravelWith(e.target.value)}>
                <option value="any">Any ride</option>
                <option value="anyone">Open to anyone</option>
                <option value="women">Women-only rides</option>
                <option value="men">Men-only rides</option>
              </select>
            </label>
            <label className="field">
              <span>Risk level</span>
              <select value={maxRisk} onChange={(e) => setMaxRisk(e.target.value)}>
                <option value="any">Any</option>
                <option value="31">Low only</option>
                <option value="51">Moderate or better</option>
                <option value="71">Below high</option>
              </select>
            </label>
          </aside>
          <section aria-live="polite">
            <div className="results-head">
              <div>
                <h2>{query.fromLabel || 'From'} → {query.toLabel || 'To'}</h2>
                <p className="muted">{fmtDate(query.date, { weekday: 'long', day: 'numeric', month: 'long' })} · {seats} seat{seats > 1 ? 's' : ''} · {loading ? 'searching…' : `${shown.length} ride${shown.length === 1 ? '' : 's'}`}</p>
              </div>
              <div className="seg" role="group" aria-label="Sort by">
                {Object.entries(SORTS).map(([k, s]) => (
                  <button key={k} className={sort === k ? 'on' : ''} onClick={() => setSort(k)}>{s.label}</button>
                ))}
              </div>
            </div>
            {error ? (
              <div className="empty">
                <h3>Couldn’t load rides</h3>
                <p>{error.message}</p>
                <button className="btn btn-primary" onClick={reload}>Try again</button>
              </div>
            ) : loading ? (
              <p className="muted">Finding rides…</p>
            ) : shown.length === 0 ? (
              <div className="empty">
                <h3>No rides match</h3>
                <p>{rides.length ? 'Try loosening the filters.' : 'Nobody has published a ride on this route and date yet. Try another date, fewer seats, or offer the ride yourself.'}</p>
              </div>
            ) : (
              <div className="ride-list">
                {shown.map((r) => <RideCard key={r.id} ride={r} />)}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
