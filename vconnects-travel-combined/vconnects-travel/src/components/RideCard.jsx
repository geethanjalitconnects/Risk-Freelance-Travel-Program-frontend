import { Link } from '../router.jsx';
import { fmtDuration, fmtPrice, fmtTime } from '../lib/format.js';
import Avatar from './Avatar.jsx';
import Icon from './Icon.jsx';
import RiskBadge from './RiskBadge.jsx';
import { DriverBadges, Rating } from './DriverTrust.jsx';

export default function RideCard({ ride }) {
  const from = ride.fromArea;
  const to = ride.toArea;
  const away = ride.match && ride.match.fromKm >= 1 ? `${Math.round(ride.match.fromKm)} km from your place` : '';
  return (
    <Link to={`/ride/${encodeURIComponent(ride.id)}`} className={`ride-card edge-${ride.risk.band.key}`}>
      <div className="rc-route">
        <div className="rc-point">
          <strong>{fmtTime(ride.depart)}</strong>
          <span>{from.name}</span>
          {away && <small className="muted">{away}</small>}
        </div>
        <div className="rc-line" aria-hidden="true">
          <span>{fmtDuration(ride.durationMin)}</span>
        </div>
        <div className="rc-point">
          <strong>{fmtTime(ride.arrive)}</strong>
          <span>{to.name}</span>
        </div>
      </div>
      <div className="rc-driver">
        <Avatar name={ride.driver.name} />
        <div>
          <div className="rc-name">{ride.driver.name}</div>
          <div className="rc-sub">
            <Rating driver={ride.driver} /> <DriverBadges driver={ride.driver} />
          </div>
        </div>
      </div>
      <div className="rc-side">
        <div className="rc-price">{fmtPrice(ride.price)}<small>/seat</small></div>
        <RiskBadge risk={ride.risk} />
        <div className="rc-meta">
          <span><Icon name="seat" size={14} /> {ride.seatsLeft} left</span>
          {ride.travelWith === 'women' && <span className="chip chip-pink">Women only</span>}
          {ride.travelWith === 'men' && <span className="chip">Men only</span>}
        </div>
      </div>
    </Link>
  );
}
