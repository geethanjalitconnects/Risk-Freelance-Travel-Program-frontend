import Avatar from './Avatar.jsx';

const STATUS = {
  confirmed: { label: 'Booked', cls: 'st-confirmed' },
  in_progress: { label: 'On the trip', cls: 'st-in_progress' },
  completed: { label: 'Completed', cls: 'st-completed' },
  pending_payment: { label: 'Awaiting payment', cls: 'st-pending_payment' },
};

// The driver's view of who booked their ride (ride.passengers, only sent to the driver).
export default function PassengerList({ passengers }) {
  if (!passengers) return null;
  if (passengers.length === 0) return <p className="muted">No bookings yet.</p>;
  return (
    <ul className="contacts">
      {passengers.map((p) => {
        const s = STATUS[p.status] || { label: p.status, cls: '' };
        const seats = `${p.seats} seat${p.seats > 1 ? 's' : ''}`;
        if (p.identityHidden) {
          // Not paid / confirmed yet: no personal details, by design (enforced by the server).
          return (
            <li key={p.bookingId}>
              <span className="muted">{seats} requested</span>
              <span className={'status-tag ' + s.cls}>{s.label}</span>
            </li>
          );
        }
        return (
          <li key={p.bookingId}>
            <span className="trip-mid" style={{ margin: 0 }}>
              <Avatar name={p.name} size={30} />
              <span><b>{p.name}</b> <span className="muted">· {seats}</span></span>
            </span>
            {p.phone && <a className="btn btn-ghost btn-call" href={`tel:${p.phone}`} aria-label={`Call ${p.name}`}>Call {p.phone}</a>}
            <span className="pl-tags">
              {p.openProblem === 'passenger_no_show' && <span className="chip chip-warn">No-show reported</span>}
              {p.openProblem && p.openProblem !== 'passenger_no_show' && <span className="chip chip-warn">Problem reported</span>}
              {p.status !== 'completed' && p.youConfirmed && <span className="chip chip-ok">You confirmed</span>}
              {p.status !== 'completed' && p.passengerConfirmed && <span className="chip chip-ok">Passenger confirmed</span>}
              <span className={'status-tag ' + s.cls}>{s.label}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}
