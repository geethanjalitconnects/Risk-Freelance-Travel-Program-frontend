import orangeCar from '../assets/car-orange.png';

// Site-wide background: faint sketched roads with orange cars cruising along them.
const ROADS = [
  { d: 'M -200 180 C 300 60, 700 360, 1200 220 S 1900 120, 2200 300', dur: 26, delay: 0 },
  { d: 'M 2200 760 C 1700 900, 1300 600, 900 720 S 200 980, -200 820', dur: 32, delay: -9 },
  { d: 'M -200 1180 C 400 1020, 900 1300, 1400 1140 S 2000 1060, 2200 1220', dur: 29, delay: -17 },
  { d: 'M 1500 -100 C 1400 300, 1700 600, 1550 1000 S 1350 1500, 1500 1700', dur: 36, delay: -5 },
];

export default function RoadBg() {
  return (
    <div className="road-bg" aria-hidden="true">
      <svg viewBox="0 0 2000 1400" preserveAspectRatio="xMidYMid slice">
        {ROADS.map((r) => (
          <g key={r.d}>
            <path d={r.d} className="road-base" />
            <path d={r.d} className="road-dash" />
          </g>
        ))}
        {ROADS.map((r, i) => (
          <image
            key={'c' + i}
            href={orangeCar}
            width="110"
            height="55"
            x="-55"
            y="-27.5"
            className="road-car"
            style={{ offsetPath: `path('${r.d}')`, animationDuration: r.dur + 's', animationDelay: r.delay + 's' }}
          />
        ))}
      </svg>
    </div>
  );
}
