import Icon from './Icon.jsx';

// Shown only when an admin has approved the driver's licence, ID and vehicle (driver.verified).
export function DriverBadges({ driver }) {
  if (!driver.verified) return null;
  return (
    <span className="trust-badges">
      <span className="trust ok" title="Licence, ID and vehicle checked by VConnects">
        <Icon name="check" size={12} /> Verified
      </span>
    </span>
  );
}

export function Rating({ driver }) {
  if (!driver.rating) return <span className="rating new">New driver</span>;
  return (
    <span className="rating">
      <Icon name="star" size={14} /> {driver.rating.toFixed(1)} <small>({driver.trips})</small>
    </span>
  );
}
