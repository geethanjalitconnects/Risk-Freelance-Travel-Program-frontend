// The last few places this browser picked, shown when a From/To field is focused while empty.
// Stays on this device only (localStorage); picking one needs no Google call.
const KEY = 'vconnects:recent-places';
const MAX = 5;

export function recentPlaces() {
  try {
    const list = JSON.parse(localStorage.getItem(KEY));
    return Array.isArray(list) ? list.filter((p) => p && p.placeId && p.label && p.area) : [];
  } catch {
    return [];
  }
}

export function rememberPlace(place) {
  if (!place?.placeId || !place.area) return;
  const { label, placeId, area } = place;
  const entry = { label, placeId, area: { code: area.code, name: area.name, district: area.district, state: area.state, region: area.region } };
  try {
    const next = [entry, ...recentPlaces().filter((p) => p.placeId !== placeId)].slice(0, MAX);
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* storage may be unavailable (private mode) */
  }
}

export function forgetRecentPlaces() {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
