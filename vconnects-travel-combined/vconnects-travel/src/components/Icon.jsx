const PATHS = {
  shield: 'M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6z',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  clock: 'M12 7v5l3 2M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
  star: 'M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z',
  pin: 'M12 21s6-5.5 6-11a6 6 0 10-12 0c0 5.5 6 11 6 11zM12 12a2 2 0 100-4 2 2 0 000 4z',
  alert: 'M12 4l9 16H3zM12 10v4M12 17v.5',
  phone: 'M6 4h3l1.5 4-2 1.5a11 11 0 006 6L16 13.5l4 1.5v3a2 2 0 01-2 2A14 14 0 014 6a2 2 0 012-2z',
  swap: 'M7 7h11l-3-3M17 17H6l3 3',
  user: 'M12 12a4 4 0 100-8 4 4 0 000 8zM4 20c0-4 4-6 8-6s8 2 8 6',
  car: 'M4 14l2-6h12l2 6v4h-2v-2H6v2H4zM7.5 14h.01M16.5 14h.01',
  moon: 'M20 14.5A8 8 0 019.5 4 8 8 0 1020 14.5z',
  cloud: 'M7 18a4 4 0 010-8 5 5 0 019.6-1A4.5 4.5 0 0117 18z',
  share: 'M12 4v11M8 8l4-4 4 4M5 14v5h14v-5',
  pulse: 'M3 12h4l2-6 4 12 2-6h6',
  route: 'M5 19a2 2 0 100-4 2 2 0 000 4zM19 9a2 2 0 100-4 2 2 0 000 4zM7 17h6a3 3 0 000-6h-2a3 3 0 010-6h6',
  bell: 'M6 17v-6a6 6 0 0112 0v6l2 2H4zM10 21h4',
  plus: 'M12 5v14M5 12h14',
  menu: 'M4 7h16M4 12h16M4 17h16',
  close: 'M6 6l12 12M18 6L6 18',
  seat: 'M8 4h5a2 2 0 012 2v6h3v4H9v4H6V6a2 2 0 012-2z',
  arrow: 'M5 12h14M13 6l6 6-6 6',
  trash: 'M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13',
};

export default function Icon({ name, size = 20, className = '' }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name] || PATHS.check} />
    </svg>
  );
}
