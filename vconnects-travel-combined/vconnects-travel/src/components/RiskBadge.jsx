import Icon from './Icon.jsx';

export default function RiskBadge({ risk, band, score, showScore = true }) {
  const b = band || risk.band;
  const s = score ?? risk.score;
  return (
    <span className={`risk-badge risk-${b.key}`} title={`Trip risk: ${b.label} (${s}/100, lower is safer)`}>
      <Icon name="shield" size={14} />
      {b.label} risk{showScore && <b>{s}</b>}
    </span>
  );
}
