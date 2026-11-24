import { useSyncExternalStore } from 'react';
import { api, ApiError, clearTokens, getTokens, onAuthLost, setTokens } from './api.js';
import { replaceProfile } from './store.js';

// Signed-in user, loaded from the API. The profile part is mirrored into the local store
// (store.js) so pages that read `profile` (Header, Publish, RideDetail, Trips) keep working.

let state = { status: 'loading', user: null, error: '' }; // status: loading | signed-in | signed-out | error
const listeners = new Set();

function set(patch) {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}

const subscribe = (l) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

export const useAuth = () => useSyncExternalStore(subscribe, () => state);

// Same options as the Profile page; women-only / men-only rides depend on this.
export const GENDER_OPTIONS = [
  { value: '', label: 'Prefer not to say' },
  { value: 'F', label: 'Female' },
  { value: 'M', label: 'Male' },
  { value: 'O', label: 'Other' },
];
export const getAuth = () => state;

function setUser(user) {
  set({ status: 'signed-in', user, error: '' });
  replaceProfile({
    name: user.name,
    phone: user.phone,
    gender: user.gender,
    verifiedId: user.verifiedId,
    verifiedLicense: user.verifiedLicense,
    contacts: user.contacts,
  });
  return user;
}

function signedOut() {
  clearTokens();
  replaceProfile({});
  set({ status: 'signed-out', user: null, error: '' });
}

onAuthLost(signedOut);

export async function loadMe() {
  if (!getTokens()) return signedOut();
  try {
    return setUser(await api.get('/me'));
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return signedOut();
    set({ status: 'error', error: e.message });
  }
}

// ---- sign-in ----
export const sendOtp = (phone) => api.post('/auth/otp/send', { phone }, { auth: false });

export async function verifyOtp(phone, code) {
  const data = await api.post('/auth/otp/verify', { phone, code }, { auth: false });
  setTokens({ access: data.access, refresh: data.refresh });
  setUser(data.user);
  return data;
}

export async function signOut() {
  const refresh = getTokens()?.refresh;
  if (refresh) {
    try {
      await api.post('/auth/logout', { refresh }, { auth: false });
    } catch {
      /* the local sign-out still happens */
    }
  }
  signedOut();
}

// ---- profile ----
export const updateMe = async (patch) => setUser(await api.patch('/me', patch));

export async function addContact(contact) {
  await api.post('/me/contacts', contact);
  return loadMe();
}

export async function removeContact(id) {
  await api.del(`/me/contacts/${id}`);
  return loadMe();
}

loadMe();
