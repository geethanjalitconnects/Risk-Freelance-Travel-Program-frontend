import { api } from './api.js';

// Driver earnings, withdrawals and the passenger's payments. All amounts are paise.
export const getEarnings = () => api.get('/me/earnings');
export const getEarningsHistory = (page = 1) => api.get(`/me/earnings/history?page=${page}`);
export const listWithdrawals = () => api.get('/me/withdrawals');
// `key` is a fresh UUID per swipe: a retry with the same key never creates a second withdrawal.
export const requestWithdrawal = (key) => api.post('/me/withdrawals', undefined, { headers: { 'Idempotency-Key': key } });
export const getMyPayments = () => api.get('/me/payments');

export const newKey = () =>
  (crypto.randomUUID ? crypto.randomUUID() : `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`);

// ₹1,234 or ₹1,234.50 from paise.
export const fmtPaise = (p) => {
  const n = Number(p || 0) / 100;
  const whole = Number.isInteger(n);
  return (n < 0 ? '-₹' : '₹') + Math.abs(n).toLocaleString('en-IN', { minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: 2 });
};

export const WITHDRAWAL_STATUS = {
  pending: 'Requested', processing: 'Processing', paid: 'Paid', failed: 'Failed, returned', rejected: 'Rejected, returned',
};
export const REFUND_STATUS = { pending: 'Refund pending', processing: 'Refund on its way', processed: 'Refunded', failed: 'Refund failed' };
