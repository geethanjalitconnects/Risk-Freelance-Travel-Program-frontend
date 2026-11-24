// Illustrated route map. The car, route line and stop markers are driven from Home.jsx on scroll
// (refs are exposed through the `refs` prop so no React re-render happens per frame).
export const ROUTE_D =
  'M 130 640 C 290 650, 300 520, 430 500 S 640 570, 690 430 S 650 250, 770 200 S 880 130, 890 96';

export const STOPS = [
  { x: 130, y: 640, label: 'Chennai', kind: 'end' },
  { x: 430, y: 500, label: '+1 rider', kind: 'mid' },
  { x: 690, y: 430, label: '+1 rider', kind: 'mid' },
  { x: 890, y: 96, label: 'Bengaluru', kind: 'end' },
];

export default function RouteScene({ refs }) {
  return (
    <svg className="route-svg" viewBox="0 0 1000 760" role="img" aria-label="Illustration of a shared car trip along a route with two pickup stops">
      <defs>
        <linearGradient id="rs-plane" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#fffaf0" />
          <stop offset="1" stopColor="#f4ecd8" />
        </linearGradient>
        <linearGradient id="rs-route" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="#0b5f59" />
          <stop offset="0.55" stopColor="#14a89a" />
          <stop offset="1" stopColor="#5eead4" />
        </linearGradient>
        <linearGradient id="rs-body" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#2fd3bf" />
          <stop offset="1" stopColor="#0b6e66" />
        </linearGradient>
        <linearGradient id="rs-roof" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#8af3e2" />
          <stop offset="1" stopColor="#18a898" />
        </linearGradient>
        <pattern id="rs-grid" width="40" height="40" patternUnits="userSpaceOnUse">
          <path d="M40 0H0V40" fill="none" stroke="#e6dcc3" strokeWidth="1" opacity="0.55" />
        </pattern>
        <filter id="rs-blur" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="7" /></filter>
      </defs>

      {/* ground plane */}
      <rect x="20" y="20" width="960" height="720" rx="46" fill="url(#rs-plane)" />
      <rect x="20" y="20" width="960" height="720" rx="46" fill="url(#rs-grid)" />
      <rect x="20" y="20" width="960" height="720" rx="46" fill="none" stroke="#e8dfca" strokeWidth="2" />

      {/* land, water, parks */}
      <path d="M60 120 C 180 60, 330 90, 360 190 S 250 330, 120 300 S 20 190 60 120Z" fill="#cfeee5" opacity="0.7" />
      <path d="M600 600 C 700 560, 860 600, 920 680 L 960 720 L 560 720 C 560 670, 570 620, 600 600Z" fill="#cdeaf0" opacity="0.7" />
      <path d="M520 90 C 600 40, 700 70, 690 140 S 560 190, 520 150Z" fill="#fde4c8" opacity="0.8" />
      <path d="M40 470 C 140 430, 200 470, 190 540 S 90 590, 50 560Z" fill="#fde4c8" opacity="0.55" />

      {/* minor roads */}
      <g fill="none" stroke="#fffdf6" strokeWidth="14" strokeLinecap="round" opacity="0.95">
        <path d="M70 380 C 280 330, 420 420, 600 330 S 860 330, 950 260" />
        <path d="M300 60 C 330 220, 280 380, 340 700" />
        <path d="M560 40 C 600 200, 560 330, 600 720" />
        <path d="M780 40 C 800 200, 760 330, 800 720" />
      </g>
      <g fill="none" stroke="#e5dbc2" strokeWidth="2" strokeDasharray="6 10" opacity="0.8">
        <path d="M70 380 C 280 330, 420 420, 600 330 S 860 330, 950 260" />
        <path d="M300 60 C 330 220, 280 380, 340 700" />
      </g>

      {/* main road bed + guide */}
      <path d={ROUTE_D} fill="none" stroke="#fffdf6" strokeWidth="30" strokeLinecap="round" />
      <path d={ROUTE_D} fill="none" stroke="#e6dcc3" strokeWidth="30" strokeLinecap="round" opacity="0.35" />
      <path d={ROUTE_D} fill="none" stroke="#d9cfb5" strokeWidth="3" strokeDasharray="4 12" strokeLinecap="round" />
      <path ref={refs.path} d={ROUTE_D} fill="none" stroke="none" />
      {/* progress line */}
      <path
        ref={refs.done}
        d={ROUTE_D}
        pathLength="1"
        fill="none"
        stroke="url(#rs-route)"
        strokeWidth="12"
        strokeLinecap="round"
        strokeDasharray="1"
        strokeDashoffset="1"
      />

      {/* stops */}
      {STOPS.map((s, i) => (
        <g key={s.label + i} className={'rs-stop rs-' + s.kind} ref={(el) => (refs.stops.current[i] = el)} transform={`translate(${s.x} ${s.y})`}>
          <circle className="rs-pulse" r="16" />
          <circle className="rs-ring" r="14" />
          <circle className="rs-core" r="7" />
          <g transform={`translate(0 ${s.kind === 'end' ? -40 : 42})`}>
            <rect x={-s.label.length * 5.2 - 14} y="-15" width={s.label.length * 10.4 + 28} height="30" rx="15" className="rs-tag" />
            <text textAnchor="middle" y="5" className="rs-tag-text">{s.label}</text>
          </g>
        </g>
      ))}

      {/* car (faces +x so rotation follows the path tangent) */}
      <g ref={refs.car} className="rs-car">
        <ellipse cx="4" cy="22" rx="46" ry="15" fill="#0b3d3b" opacity="0.28" filter="url(#rs-blur)" />
        <rect x="-44" y="-21" width="88" height="42" rx="15" fill="url(#rs-body)" />
        <rect x="-44" y="-21" width="88" height="42" rx="15" fill="none" stroke="#ffffff" strokeOpacity="0.35" strokeWidth="1.5" />
        <path d="M-26 -16 H 6 Q 16 -16 22 -9 L 28 0 L 22 9 Q 16 16 6 16 H -26 Q -32 16 -32 10 V -10 Q -32 -16 -26 -16Z" fill="url(#rs-roof)" />
        <path d="M10 -15 Q 20 -14 26 -6 L 30 0 L 26 6 Q 20 14 10 15Z" fill="#0b3d3b" opacity="0.88" />
        <path d="M-30 -12 H -18 V 12 H -30Z" fill="#0b3d3b" opacity="0.78" />
        <rect x="-8" y="-9" width="12" height="18" rx="5" fill="#ffffff" opacity="0.5" />
        <rect x="-45" y="-17" width="5" height="9" rx="2.5" fill="#f97316" />
        <rect x="-45" y="8" width="5" height="9" rx="2.5" fill="#f97316" />
        <rect x="39" y="-17" width="6" height="9" rx="3" fill="#fff5d6" />
        <rect x="39" y="8" width="6" height="9" rx="3" fill="#fff5d6" />
        <rect x="-13" y="-6" width="12" height="12" rx="6" fill="#f97316" opacity="0.95" />
      </g>
    </svg>
  );
}
