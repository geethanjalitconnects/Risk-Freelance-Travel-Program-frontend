import { hashString } from '../lib/seed.js';
import { initials } from '../lib/format.js';

const COLORS = ['#0f766e', '#14a89a', '#ea580c', '#b45309', '#0b5f59', '#c2410c', '#0d9488'];

export default function Avatar({ name, size = 40 }) {
  const color = COLORS[hashString(name || '?') % COLORS.length];
  return (
    <span className="avatar" style={{ width: size, height: size, background: color, fontSize: size * 0.38 }} aria-hidden="true">
      {initials(name)}
    </span>
  );
}
