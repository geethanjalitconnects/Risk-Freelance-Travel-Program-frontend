import { bandFor } from '../lib/risk.js';
import Icon from './Icon.jsx';

export function ScoreDial({ risk, size = 120 }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  const pct = Math.min(100, risk.score) / 100;
  return (
    <div className={`dial risk-${risk.band.key}`} style={{ width: size, height: size }}>
      <svg viewBox="0 0 120 120" width={size} height={size} role="img" aria-label={`Risk score ${risk.score} out of 100, ${risk.band.label}`}>
        <circle cx="60" cy="60" r={r} className="dial-track" />
        <circle
          cx="60"
          cy="60"
          r={r}
          className="dial-arc"
          strokeDasharray={`${c * pct} ${c}`}
          transform="rotate(-90 60 60)"
        />
      </svg>
      <div className="dial-text">
        <strong>{risk.score}</strong>
        <span>{risk.band.label}</span>
      </div>
    </div>
  );
}

export default function RiskBreakdown({ risk, compact = false }) {
  return (
    <div className="risk-breakdown">
      <div className="rb-head">
        <ScoreDial risk={risk} />
        <div>
          <h3>Trip risk: {risk.band.label}</h3>
          <p className="muted">
            Score {risk.score}/100, where lower is safer. It blends route, time of day, driver, weather, drive
            length and vehicle.
          </p>
        </div>
      </div>
      <ul className="rb-list">
        {risk.components.map((c) => {
          const band = bandFor(c.value);
          return (
            <li key={c.key}>
              <div className="rb-row">
                <span className="rb-label">{c.label}</span>
                <span className="rb-weight">{Math.round(c.weight * 100)}% weight</span>
                <span className={`rb-val risk-text-${band.key}`}>{c.value}</span>
              </div>
              <div className="rb-bar" aria-hidden="true">
                <span className={`risk-fill-${band.key}`} style={{ width: `${c.value}%` }} />
              </div>
              {!compact && <p className="rb-detail">{c.detail}</p>}
            </li>
          );
        })}
      </ul>
      {!compact && (
        <div className="rb-tips">
          <h4>
            <Icon name="shield" size={16} /> Ways to travel safer on this trip
          </h4>
          <ul>
            {risk.tips.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
