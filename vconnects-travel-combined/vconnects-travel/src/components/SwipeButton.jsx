import { useRef, useState } from 'react';
import Icon from './Icon.jsx';

const HANDLE = 52; // px, keep in step with .swipe-handle in pages.css
const THRESHOLD = 0.85; // how far (of the track) the handle must travel to confirm

// Swipe-to-confirm for actions that move money or close a trip (complete a ride, withdraw).
// - Drag the handle with a finger or mouse (pointer events), or focus it and press Enter / Space.
// - `onConfirm` must return a promise; it runs once (double swipes and taps are ignored while it
//   is in flight) and a rejection shows its message and resets the slider so the user can retry.
export default function SwipeButton({ label, busyLabel = 'Working…', doneLabel = 'Done', onConfirm, disabled = false }) {
  const track = useRef(null);
  const drag = useRef(null);
  const inFlight = useRef(false);
  const [x, setX] = useState(0);
  const [state, setState] = useState('idle'); // idle | busy | done | error
  const [error, setError] = useState('');

  const max = () => (track.current ? track.current.clientWidth - HANDLE - 8 : 0);
  const locked = disabled || state === 'busy' || state === 'done';

  async function fire() {
    if (locked || inFlight.current) return;
    inFlight.current = true;
    setError('');
    setState('busy');
    setX(max());
    try {
      await onConfirm();
      setState('done');
    } catch (e) {
      setError(e?.message || 'Something went wrong. Please try again.');
      setState('error');
      setX(0);
      inFlight.current = false;
    }
  }

  function onPointerDown(e) {
    if (locked) return;
    drag.current = { start: e.clientX - x };
    e.currentTarget.setPointerCapture(e.pointerId);
  }

  function onPointerMove(e) {
    if (!drag.current) return;
    setX(Math.min(max(), Math.max(0, e.clientX - drag.current.start)));
  }

  function onPointerUp() {
    if (!drag.current) return;
    drag.current = null;
    if (x >= max() * THRESHOLD) fire();
    else setX(0);
  }

  const text = state === 'busy' ? busyLabel : state === 'done' ? doneLabel : label;

  return (
    <div className="swipe-wrap">
      <div ref={track} className={`swipe swipe-${state}${disabled ? ' swipe-disabled' : ''}`}>
        <span className="swipe-fill" style={{ width: x + HANDLE }} aria-hidden="true" />
        <span className="swipe-label" aria-hidden="true">{text}</span>
        <button
          type="button"
          className="swipe-handle"
          style={{ transform: `translateX(${x}px)`, transition: drag.current ? 'none' : undefined }}
          disabled={locked}
          aria-label={`${label}. Swipe right, or press Enter to confirm.`}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          // Keyboard activation (Enter / Space) is a click with detail 0; mouse clicks after a drag are ignored.
          onClick={(e) => e.detail === 0 && fire()}
        >
          <Icon name={state === 'done' ? 'check' : 'arrow'} size={20} />
        </button>
      </div>
      <p className="sr-only" aria-live="polite">{state === 'idle' ? '' : text}</p>
      {error && <p className="form-error" role="alert">{error}</p>}
    </div>
  );
}
