// Small client for the VConnects Django API.
// Set VITE_API_URL to point at another server (default: local Django dev server).
const BASE = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api/v1').replace(/\/$/, '');
const TOKENS_KEY = 'vconnects:auth';

export function getTokens() {
  try {
    return JSON.parse(localStorage.getItem(TOKENS_KEY)) || null;
  } catch {
    return null;
  }
}

export function setTokens(tokens) {
  try {
    localStorage.setItem(TOKENS_KEY, JSON.stringify(tokens));
  } catch {
    /* storage may be unavailable */
  }
}

export function clearTokens() {
  try {
    localStorage.removeItem(TOKENS_KEY);
  } catch {
    /* ignore */
  }
}

export class ApiError extends Error {
  constructor(status, data) {
    super(ApiError.messageFrom(data) || (status ? 'Something went wrong. Please try again.' : "Can't reach the server. Check your connection."));
    this.status = status;
    this.data = data || {};
  }

  // First readable message: "detail", then the first field or form error.
  static messageFrom(data) {
    if (!data || typeof data !== 'object') return '';
    if (typeof data.detail === 'string') return data.detail;
    for (const value of Object.values(data)) {
      if (typeof value === 'string') return value;
      if (Array.isArray(value) && typeof value[0] === 'string') return value[0];
      if (value && typeof value === 'object') {
        const nested = ApiError.messageFrom(value);
        if (nested) return nested;
      }
    }
    return '';
  }

  // Message for one field, e.g. err.field('phone').
  field(name) {
    const v = this.data[name];
    return Array.isArray(v) ? v[0] : typeof v === 'string' ? v : '';
  }
}

let authLostHandler = () => {};
export const onAuthLost = (fn) => {
  authLostHandler = fn;
};

let refreshing = null;
function refreshTokens() {
  // One refresh at a time, shared by every request that hit a 401.
  if (!refreshing) {
    const tokens = getTokens();
    refreshing = (async () => {
      if (!tokens?.refresh) return false;
      try {
        const res = await fetch(`${BASE}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh: tokens.refresh }),
        });
        if (!res.ok) return false;
        const data = await res.json();
        setTokens({ access: data.access, refresh: data.refresh || tokens.refresh });
        return true;
      } catch {
        return false;
      }
    })().finally(() => {
      refreshing = null;
    });
  }
  return refreshing;
}

async function request(path, { method = 'GET', body, auth = true, retry = true, headers: extra, signal } = {}) {
  const headers = { Accept: 'application/json', ...extra };
  // FormData (file uploads) is sent as-is so the browser sets the multipart boundary.
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
  if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json';
  const tokens = getTokens();
  if (auth && tokens?.access) headers.Authorization = `Bearer ${tokens.access}`;

  let res;
  try {
    res = await fetch(BASE + path, { method, headers, signal, body: body === undefined ? undefined : isForm ? body : JSON.stringify(body) });
  } catch (e) {
    if (signal?.aborted) throw e; // cancelled by the caller (AbortController), not a network error
    throw new ApiError(0, null);
  }

  if (res.status === 401 && auth && tokens?.refresh && retry) {
    if (await refreshTokens()) return request(path, { method, body, auth, retry: false, headers: extra, signal });
    clearTokens();
    authLostHandler();
  }

  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

export const api = {
  get: (path, opts) => request(path, opts),
  post: (path, body, opts) => request(path, { ...opts, method: 'POST', body }),
  patch: (path, body, opts) => request(path, { ...opts, method: 'PATCH', body }),
  put: (path, body, opts) => request(path, { ...opts, method: 'PUT', body }),
  del: (path, opts) => request(path, { ...opts, method: 'DELETE' }),
};
