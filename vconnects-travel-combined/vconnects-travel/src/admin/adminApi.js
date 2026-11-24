// Admin dashboard client. Completely separate from the user app's auth (lib/api.js, lib/auth.js):
// its own API base (/api/admin), its own token, kept in sessionStorage under its own key. The
// server signs admin tokens with a different secret, so neither token works on the other API.
import { useSyncExternalStore } from 'react';
import { navigate } from '../router.jsx';

const USER_API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api/v1';
const BASE = (import.meta.env.VITE_ADMIN_API_URL || USER_API.replace(/\/api\/v1\/?$/, '/api/admin')).replace(/\/$/, '');
const KEY = 'vconnects:admin-session';

// ---------------------------------------------------------------- session store

function read() {
  try {
    const s = JSON.parse(sessionStorage.getItem(KEY));
    return s && s.token && s.expiresAt > Date.now() ? s : null;
  } catch {
    return null;
  }
}

let session = read();
const listeners = new Set();

function setSession(next) {
  session = next;
  try {
    if (next) sessionStorage.setItem(KEY, JSON.stringify(next));
    else sessionStorage.removeItem(KEY);
  } catch {
    /* storage blocked: the session lasts until the tab reloads */
  }
  listeners.forEach((l) => l());
}

export const getSession = () => (session && session.expiresAt > Date.now() ? session : null);
export const useAdminSession = () =>
  useSyncExternalStore(
    (l) => { listeners.add(l); return () => listeners.delete(l); },
    () => session,
  );

// ---------------------------------------------------------------- requests

export class AdminError extends Error {
  constructor(status, data) {
    super(AdminError.messageFrom(data) || (status ? 'Something went wrong. Please try again.' : "Can't reach the server."));
    this.status = status;
    this.data = data || {};
  }

  static messageFrom(data) {
    if (!data || typeof data !== 'object') return '';
    if (typeof data.detail === 'string') return data.detail;
    for (const v of Object.values(data)) {
      if (typeof v === 'string') return v;
      if (Array.isArray(v) && typeof v[0] === 'string') return v[0];
    }
    return '';
  }

  field(name) {
    const v = this.data[name];
    return Array.isArray(v) ? v[0] : typeof v === 'string' ? v : '';
  }
}

async function request(path, { method = 'GET', body, blob = false, auth = true } = {}) {
  const headers = { Accept: blob ? '*/*' : 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const s = getSession();
  if (auth && s) headers.Authorization = `Bearer ${s.token}`;
  let res;
  try {
    res = await fetch(BASE + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store' });
  } catch {
    throw new AdminError(0, null);
  }
  if (res.status === 401 && auth) {
    setSession(null);
    navigate('/admin/login');
  }
  if (res.status === 204) return null;
  if (blob && res.ok) return res.blob();
  const data = await res.json().catch(() => null);
  if (res.status === 403 && data?.code === 'password_change_required') navigate('/admin/password');
  if (!res.ok) throw new AdminError(res.status, data);
  return data;
}

const get = (p) => request(p);
const post = (p, body = {}) => request(p, { method: 'POST', body });

// ---------------------------------------------------------------- auth

export async function login(username, password) {
  const data = await request('/login', { method: 'POST', body: { username, password }, auth: false });
  setSession(data);
  return data;
}

export async function changePassword(currentPassword, newPassword) {
  const data = await post('/password', { currentPassword, newPassword });
  setSession(data);
  return data;
}

export async function logout() {
  try {
    await post('/logout');
  } catch {
    /* signing out locally still happens */
  }
  setSession(null);
  navigate('/admin/login');
}

// ---------------------------------------------------------------- review

export const getQueue = ({ status = 'pending', q = '', page = 1 } = {}) =>
  get(`/queue?${new URLSearchParams({ status, q, page })}`);
export const getReview = (userId) => get(`/review/${userId}`);
export const getDocumentBlob = (docId) => request(`/documents/${docId}/file`, { blob: true });

const r = (userId, action, body) => post(`/review/${userId}/${action}`, body);
export const approveDocument = (userId, docId) => r(userId, `documents/${docId}/approve`);
export const rejectDocument = (userId, docId, reason) => r(userId, `documents/${docId}/reject`, { reason });
export const approveProfile = (userId, aadhaarMaskedConfirmed) => r(userId, 'approve', { aadhaarMaskedConfirmed });
export const rejectProfile = (userId, reason, unmaskedAadhaar) => r(userId, 'reject', { reason, unmaskedAadhaar });
export const requestResubmit = (userId, note) => r(userId, 'request-resubmit', { note });
export const revokeProfile = (userId, reason) => r(userId, 'revoke', { reason });
export const retryEmail = (emailId) => post(`/emails/${emailId}/retry`);

export const getAudit = ({ page = 1, action = '' } = {}) => get(`/audit?${new URLSearchParams({ page, action })}`);

// ---------------------------------------------------------------- display helpers

export const STATUS_LABEL = {
  not_submitted: 'Not submitted',
  pending: 'Pending review',
  approved: 'Approved',
  rejected: 'Rejected',
  resubmit_requested: 'Re-upload requested',
  revoked: 'Revoked',
};

export function fmtWhen(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}
