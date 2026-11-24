import { api } from './api.js';

// Driver verification: vehicle number + driving licence (front, back) + one government ID.
export const getVerification = () => api.get('/me/driver-verification');
export const submitVerification = (formData) => api.post('/me/driver-verification', formData);
// Upload one new or replacement document (e.g. one the reviewer rejected).
export const uploadDocument = (kind, formData) => api.post(`/me/driver-verification/documents/${kind}`, formData);

export const ID_TYPES = [
  { value: 'aadhaar', label: 'Aadhaar (masked copy only)' },
  { value: 'pan', label: 'PAN card' },
  { value: 'voter_id', label: 'Voter ID' },
  { value: 'passport', label: 'Passport (photo page)' },
];

export const STATUS_TEXT = {
  not_submitted: 'Not submitted',
  pending: 'Pending review',
  approved: 'Approved',
  rejected: 'Rejected',
  resubmit_requested: 'Re-upload requested',
  revoked: 'Revoked',
};

export const MAX_FILE_BYTES = 5 * 1024 * 1024;
export const ACCEPT = '.jpg,.jpeg,.png,.pdf,image/jpeg,image/png,application/pdf';
const OK_TYPES = ['image/jpeg', 'image/png', 'application/pdf'];
const OK_EXT = /\.(jpe?g|png|pdf)$/i;

// Client-side check only; the server checks the real file type from its contents.
export function fileError(file, required) {
  if (!file) return required ? 'Choose a file.' : '';
  if (!(OK_TYPES.includes(file.type) || OK_EXT.test(file.name))) return 'Upload a JPG, PNG or PDF file.';
  if (file.size > MAX_FILE_BYTES) return 'Each file must be 5 MB or smaller.';
  if (file.size === 0) return 'The file is empty.';
  return '';
}

// "TN09AB1234" -> "TN 09 AB 1234", "22BH1234AA" -> "22 BH 1234 AA"
export function fmtPlate(plate = '') {
  const bh = plate.match(/^(\d{2})(BH)(\d{4})([A-Z]{1,2})$/);
  if (bh) return bh.slice(1).join(' ');
  const std = plate.match(/^([A-Z]{2})(\d{1,2})([A-Z]{0,3})(\d{1,4})$/);
  return std ? std.slice(1).filter(Boolean).join(' ') : plate;
}
