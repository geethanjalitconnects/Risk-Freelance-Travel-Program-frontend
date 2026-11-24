import { useSyncExternalStore } from 'react';
import { uid } from './format.js';

// Tiny persisted store (localStorage). Stands in for a backend in this demo.
const KEY = 'vconnects:v1';

const defaultState = () => ({
  profile: { name: '', phone: '', gender: '', verifiedId: false, verifiedLicense: false, contacts: [] },
  published: [],
  bookings: [],
});

function load() {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const saved = JSON.parse(raw);
      const base = defaultState();
      return { ...base, ...saved, profile: { ...base.profile, ...(saved.profile || {}) } };
    }
  } catch {
    /* ignore corrupt storage */
  }
  return defaultState();
}

let state = load();
const listeners = new Set();

function commit(next) {
  state = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    /* storage may be unavailable */
  }
  listeners.forEach((l) => l());
}

const subscribe = (l) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

export function useStore(selector = (s) => s) {
  return selector(useSyncExternalStore(subscribe, () => state));
}

export const getState = () => state;

// ---- profile ----
export const saveProfile = (patch) => commit({ ...state, profile: { ...state.profile, ...patch } });

// Replace the whole profile with the signed-in user's server copy (see auth.js); {} clears it.
export const replaceProfile = (profile) => commit({ ...state, profile: { ...defaultState().profile, ...profile } });

export const addContact = (contact) =>
  commit({
    ...state,
    profile: { ...state.profile, contacts: [...state.profile.contacts, { id: uid('c'), ...contact }] },
  });

export const removeContact = (id) =>
  commit({
    ...state,
    profile: { ...state.profile, contacts: state.profile.contacts.filter((c) => c.id !== id) },
  });

// ---- published rides ----
export function publishRide(ride) {
  commit({ ...state, published: [...state.published, ride] });
  return ride;
}

export const removePublished = (id) =>
  commit({ ...state, published: state.published.filter((r) => r.id !== id) });

// ---- bookings & live trips ----
const updateBooking = (id, fn) =>
  commit({ ...state, bookings: state.bookings.map((b) => (b.id === id ? fn(b) : b)) });

const withEvent = (b, type, text) => ({
  ...b,
  events: [...(b.events || []), { t: Date.now(), type, text }],
});

export function bookRide(ride, seats) {
  const { risk, ...snapshot } = ride;
  const booking = {
    id: uid('bk'),
    rideId: ride.id,
    ride: snapshot,
    riskScore: risk.score,
    riskBand: risk.band.key,
    seats,
    total: ride.price * seats,
    createdAt: Date.now(),
    status: 'confirmed',
    trip: null,
    events: [{ t: Date.now(), type: 'booked', text: `Booked ${seats} seat${seats > 1 ? 's' : ''}.` }],
    rating: null,
  };
  commit({ ...state, bookings: [...state.bookings, booking] });
  return booking;
}

export const cancelBooking = (id) =>
  updateBooking(id, (b) => withEvent({ ...b, status: 'cancelled' }, 'cancelled', 'Booking cancelled.'));

export const startTrip = (id) =>
  updateBooking(id, (b) =>
    withEvent(
      { ...b, status: 'in_progress', trip: { startedAt: Date.now(), checkins: {}, missed: {}, shared: false, sos: null } },
      'started',
      'Trip started. Check-ins are on.'
    )
  );

export const checkIn = (id, key, label) =>
  updateBooking(id, (b) =>
    withEvent({ ...b, trip: { ...b.trip, checkins: { ...b.trip.checkins, [key]: Date.now() } } }, 'checkin', `Checked in: ${label}.`)
  );

export const markMissed = (id, key, label) =>
  updateBooking(id, (b) =>
    b.trip?.missed?.[key]
      ? b
      : withEvent(
          { ...b, trip: { ...b.trip, missed: { ...b.trip.missed, [key]: Date.now() } } },
          'missed',
          `Missed check-in: ${label}. Contacts would be alerted.`
        )
  );

export const shareTrip = (id) =>
  updateBooking(id, (b) =>
    withEvent({ ...b, trip: { ...b.trip, shared: true } }, 'shared', 'Live trip link shared with contacts.')
  );

export const triggerSos = (id) =>
  updateBooking(id, (b) =>
    withEvent({ ...b, trip: { ...b.trip, sos: Date.now() } }, 'sos', 'SOS raised. Contacts and helplines shown.')
  );

export const endTrip = (id) =>
  updateBooking(id, (b) => withEvent({ ...b, status: 'completed', completedAt: Date.now() }, 'completed', 'Arrived safely.'));

export const rateTrip = (id, stars) =>
  updateBooking(id, (b) => withEvent({ ...b, rating: stars }, 'rated', `Rated the driver ${stars}/5.`));

export const resetDemo = () => commit(defaultState());
