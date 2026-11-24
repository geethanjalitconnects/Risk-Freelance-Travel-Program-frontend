import { api } from './api.js';

// Google Places goes through our Django proxy only: the browser never sees the API key.

// One token per search session (per field), renewed after each pick. UUID v4 fits Google's
// "URL-safe, at most 36 characters" rule.
export function newSession() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID();
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

const q = (params) => new URLSearchParams(params).toString();

// -> { suggestions: [{ placeId, text, main, secondary }], attribution }
export const placesAutocomplete = (text, session, signal) =>
  api.get(`/places/autocomplete?${q({ q: text, session })}`, { auth: false, signal });

// -> { placeId, area: { code, name, district, state, region, meetingPoints } }
export const placeDetails = (placeId, session, signal) =>
  api.get(`/places/details?${q({ placeId, session })}`, { auth: false, signal });

// "Use my current location": the area-level place at a position (not stored by the server).
// -> { placeId, label, area }
export const reversePlace = (lat, lng) =>
  api.get(`/places/reverse?${q({ lat: lat.toFixed(6), lng: lng.toFixed(6) })}`, { auth: false });

// An area (taluk) with its meeting points, for rides whose place was picked earlier.
export const getArea = (code) => api.get(`/areas/${encodeURIComponent(code)}`);

// Switched off, misconfigured, Google down or no network.
export const placesUnavailable = (err) => err?.status === 503 || err?.status === 0;
