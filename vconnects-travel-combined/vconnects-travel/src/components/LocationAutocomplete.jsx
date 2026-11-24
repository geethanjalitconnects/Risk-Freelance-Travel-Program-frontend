import { useEffect, useId, useRef, useState } from 'react';
import { newSession, placeDetails, placesAutocomplete, placesUnavailable, reversePlace } from '../lib/placesApi.js';
import { forgetRecentPlaces, recentPlaces, rememberPlace } from '../lib/recentPlaces.js';
import Icon from './Icon.jsx';

const DEBOUNCE_MS = 400;
const MIN_CHARS = 3;
const UNAVAILABLE = 'Location search is unavailable right now. Please try again in a moment.';

/**
 * From/To place picker (Google Places through our backend). The user must pick a suggestion:
 * typing alone never produces a value.
 *
 * value / onChange: null, or { label, placeId, area: { code, name, district, state, region, meetingPoints } }.
 * `label` is the picked suggestion's main text; `area` is the taluk the place belongs to.
 */
export default function LocationAutocomplete({
  label, value, onChange, placeholder = 'Area, town or city', disabled = false, className = 'sf-field', invalid = false,
  currentLocation = false, // offer "Use my current location" when the field is empty
}) {
  const id = useId();
  const listId = `${id}-list`;
  const [text, setText] = useState(value?.label || '');
  const [items, setItems] = useState([]); // {key, main, secondary, placeId, recent?}
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [status, setStatus] = useState('idle'); // idle | loading | ready | empty | error | checking
  const [message, setMessage] = useState('');
  const session = useRef(null);
  const controller = useRef(null);
  const timer = useRef(null);
  const inputRef = useRef(null);
  const emitted = useRef(value); // the last value this field reported itself

  function emit(v) {
    emitted.current = v;
    onChange(v);
  }

  // Changes made outside (swap button, editing an existing ride) replace the text;
  // our own emit(null) while typing must not wipe what the user is typing.
  useEffect(() => {
    if (value !== emitted.current) {
      emitted.current = value;
      setText(value?.label || '');
      setMessage('');
      setStatus('idle');
    }
  }, [value]);
  useEffect(() => () => { clearTimeout(timer.current); controller.current?.abort(); }, []);

  function cancel() {
    clearTimeout(timer.current);
    controller.current?.abort();
    controller.current = null;
  }

  function search(t) {
    cancel();
    setMessage('');
    const q = t.trim();
    if (q.length < MIN_CHARS) {
      setItems([]);
      setStatus('idle');
      setOpen(q.length > 0);
      return;
    }
    setStatus('loading');
    setOpen(true);
    timer.current = setTimeout(async () => {
      const ctrl = new AbortController();
      controller.current = ctrl;
      if (!session.current) session.current = newSession();
      try {
        const res = await placesAutocomplete(q, session.current, ctrl.signal);
        if (ctrl.signal.aborted) return;
        const rows = res.suggestions.map((s) => ({ key: s.placeId, main: s.main, secondary: s.secondary, placeId: s.placeId }));
        setItems(rows);
        setStatus(rows.length ? 'ready' : 'empty');
        setActive(rows.length ? 0 : -1);
      } catch (e) {
        if (ctrl.signal.aborted || e?.name === 'AbortError') return;
        setItems([]);
        setStatus('error');
        setMessage(placesUnavailable(e) ? UNAVAILABLE : e.message);
      }
    }, DEBOUNCE_MS);
  }

  // Empty field: offer this device's recent places (no Google call).
  function showRecent() {
    const here = currentLocation && 'geolocation' in navigator
      ? [{ key: 'here', main: 'Use my current location', secondary: 'Asks your browser for permission', here: true }] : [];
    const rows = [...here, ...recentPlaces().map((p) => ({ key: 'r-' + p.placeId, main: p.label, secondary: p.area.region, placeId: p.placeId, recent: p }))];
    setItems(rows);
    setStatus(rows.length ? 'recent' : 'idle');
    setActive(-1);
    setOpen(rows.length > 0);
  }

  function onInput(e) {
    const t = e.target.value;
    setText(t);
    if (value) emit(null); // editing the text drops the previous pick
    if (!t.trim()) { cancel(); showRecent(); return; }
    search(t);
  }

  // Browser position -> our backend (Google reverse geocoding) -> an area-level place.
  function locate() {
    setStatus('checking');
    setMessage('Finding your location…');
    navigator.geolocation.getCurrentPosition(
      async ({ coords }) => {
        try {
          const res = await reversePlace(coords.latitude, coords.longitude);
          const picked = { label: res.label, placeId: res.placeId, area: res.area };
          setText(res.label);
          setStatus('idle');
          setMessage('');
          emit(picked);
          rememberPlace(picked);
        } catch (e) {
          setStatus('error');
          setMessage(placesUnavailable(e) ? UNAVAILABLE : e.message);
        }
      },
      (err) => {
        setStatus('error');
        setMessage(err.code === 1
          ? 'Location permission was denied. Please type a place instead.'
          : "We couldn't get your location. Please type a place instead.");
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 },
    );
  }

  async function pick(item) {
    cancel();
    setOpen(false);
    setActive(-1);
    if (item.here) { locate(); return; }
    setText(item.main);
    if (item.recent) {
      setStatus('idle');
      setMessage('');
      emit(item.recent);
      rememberPlace(item.recent);
      return;
    }
    setStatus('checking');
    setMessage('');
    const token = session.current;
    session.current = null; // the details call closes this session; the next search starts a new one
    try {
      const res = await placeDetails(item.placeId, token || newSession());
      setStatus('idle');
      const picked = { label: item.main, placeId: res.placeId, area: res.area };
      emit(picked);
      rememberPlace(picked);
    } catch (e) {
      emit(null);
      setStatus('error');
      setMessage(placesUnavailable(e) ? UNAVAILABLE : e.message);
    }
  }

  function onKeyDown(e) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!open) { if (text.trim()) search(text); else showRecent(); return; }
      if (!items.length) return;
      const step = e.key === 'ArrowDown' ? 1 : -1;
      setActive((i) => (i + step + items.length) % items.length);
    } else if (e.key === 'Enter') {
      if (open && active >= 0 && items[active]) {
        e.preventDefault(); // pick, don't submit the form
        pick(items[active]);
      } else if (!value && text) {
        e.preventDefault();
        setMessage('Please pick a place from the suggestions.');
      }
    } else if (e.key === 'Escape') {
      if (open) { e.preventDefault(); setOpen(false); cancel(); }
    }
  }

  function clear() {
    cancel();
    setText('');
    setItems([]);
    setStatus('idle');
    setMessage('');
    setOpen(false);
    emit(null);
    inputRef.current?.focus();
    showRecent();
  }

  const showMin = status === 'idle' && text.trim().length > 0 && text.trim().length < MIN_CHARS;
  const listVisible = open && !disabled && (items.length > 0 || status === 'loading' || status === 'empty' || showMin);
  const isRecent = status === 'recent';
  const unpicked = !value && text && status !== 'checking' && status !== 'error' && !open;
  const live = status === 'loading' ? 'Searching…'
    : status === 'checking' ? 'Checking this place…'
    : status === 'empty' ? 'No places found.'
    : status === 'ready' && open ? `${items.length} suggestion${items.length === 1 ? '' : 's'}. Use up and down arrows to choose.`
    : '';
  const hint = message || (unpicked ? 'Please pick a place from the suggestions.' : value?.area?.region || '');

  return (
    <div className={className + ' loc-ac'}>
      <label htmlFor={id}><span>{label}</span></label>
      <div className="loc-ac-box">
        <Icon name="pin" size={16} />
        <input
          id={id}
          ref={inputRef}
          type="text"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={listVisible}
          aria-controls={listId}
          aria-activedescendant={listVisible && active >= 0 ? `${id}-opt-${active}` : undefined}
          aria-invalid={invalid || Boolean(unpicked) || status === 'error' || undefined}
          aria-describedby={hint ? `${id}-msg` : undefined}
          value={text}
          placeholder={placeholder}
          disabled={disabled}
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          enterKeyHint="search"
          onChange={onInput}
          onKeyDown={onKeyDown}
          onFocus={() => { if (!value) (text ? search(text) : showRecent()); }}
          onBlur={() => setTimeout(() => setOpen(false), 120)}
        />
        {status === 'loading' || status === 'checking' ? <span className="loc-ac-spin" aria-hidden="true" /> : null}
        {text && !disabled && (
          <button type="button" className="loc-ac-clear" aria-label={`Clear ${label}`} onClick={clear}>
            <Icon name="close" size={16} />
          </button>
        )}
      </div>

      {listVisible && (
        <ul id={listId} role="listbox" aria-label={`${label} suggestions`} className="loc-ac-list">
          {showMin && <li className="loc-ac-note" role="presentation">Type at least {MIN_CHARS} letters</li>}
          {status === 'loading' && !items.length && <li className="loc-ac-note" role="presentation">Searching…</li>}
          {status === 'empty' && <li className="loc-ac-note" role="presentation">No places found. Try a nearby town or area.</li>}
          {items.map((it, i) => (
            <li
              key={it.key}
              id={`${id}-opt-${i}`}
              role="option"
              aria-selected={i === active}
              className={'loc-ac-opt' + (i === active ? ' active' : '')}
              onPointerDown={(e) => e.preventDefault()} // keep focus in the input until the pick
              onClick={() => pick(it)}
              onMouseEnter={() => setActive(i)}
            >
              {it.recent && i === items.findIndex((x) => x.recent) && <span className="loc-ac-head" aria-hidden="true">Recent places</span>}
              <span className="loc-ac-main">
                {it.here && <Icon name="pin" size={13} />}{it.recent && <Icon name="clock" size={13} />} {it.main}
              </span>
              {it.secondary && <span className="loc-ac-sub">{it.secondary}</span>}
            </li>
          ))}
          {isRecent && items.some((x) => x.recent) && (
            <li className="loc-ac-attr" role="presentation">
              <button type="button" className="link-btn" onPointerDown={(e) => e.preventDefault()}
                onClick={() => { forgetRecentPlaces(); setItems([]); setOpen(false); setStatus('idle'); }}>Clear recent</button>
            </li>
          )}
          {!isRecent && items.length > 0 && (
            <li className="loc-ac-attr" role="presentation"><span translate="no">Google Maps</span></li>
          )}
        </ul>
      )}

      <span className="sr-only" aria-live="polite">{live}</span>
      {hint && (
        <span id={`${id}-msg`} className={'loc-ac-msg' + (status === 'error' || unpicked ? ' err' : '')}>{hint}</span>
      )}
    </div>
  );
}
