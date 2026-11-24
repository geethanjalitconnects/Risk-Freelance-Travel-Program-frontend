import { api } from './api.js';

// Payout details (bank account or UPI) for drivers. The server only ever returns masked values.
// GET/PUT both return { account: {...} | null, canEdit }.
export const getPayoutAccount = () => api.get('/me/payout-account');
export const savePayoutAccount = (body) => api.put('/me/payout-account', body);

export const PAYOUT_STATUS = {
  pending: 'Pending verification',
  verified: 'Verified',
  failed: 'Verification failed',
};

// Same rules as the server (apps/payments/validators.py), for instant feedback.
export const IFSC_RE = /^[A-Z]{4}0[A-Z0-9]{6}$/;
export const ACCOUNT_RE = /^\d{9,18}$/;
export const UPI_RE = /^[a-z0-9][a-z0-9.\-_]{1,255}@[a-z][a-z0-9]{1,63}$/i;
export const digitsOnly = (s) => s.replace(/[\s-]/g, '');
