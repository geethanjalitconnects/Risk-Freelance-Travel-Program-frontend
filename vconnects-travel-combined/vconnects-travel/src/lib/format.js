const pad = (n) => String(n).padStart(2, '0');

export const toIsoLocal = (d) =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;

export const todayStr = () => toIsoLocal(new Date()).slice(0, 10);

export const addDays = (dateStr, n) => {
  const d = new Date(dateStr + 'T00:00');
  d.setDate(d.getDate() + n);
  return toIsoLocal(d).slice(0, 10);
};

export const addMinutes = (iso, m) => toIsoLocal(new Date(new Date(iso).getTime() + m * 60000));

export const fmtTime = (iso) => {
  const d = new Date(iso);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

export const fmtDate = (dateStr, opts) =>
  new Date(dateStr + 'T00:00').toLocaleDateString('en-IN', opts || { weekday: 'short', day: 'numeric', month: 'short' });

export const fmtDateTime = (iso) => `${fmtDate(iso.slice(0, 10))}, ${fmtTime(iso)}`;

export const fmtDuration = (min) => {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h ? `${h}h${m ? ` ${m}m` : ''}` : `${m}m`;
};

export const fmtPrice = (n) => '₹' + Number(n).toLocaleString('en-IN');

export const initials = (name = '') =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0].toUpperCase())
    .join('') || '?';

export const uid = (prefix) => prefix + '-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
