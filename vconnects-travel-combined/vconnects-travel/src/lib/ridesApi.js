import { api } from './api.js';

// Rides and bookings on the VConnects API. Objects keep the shapes the pages already used.

export const searchRides = ({ from, to, date, seats = 1 }) =>
  api.get('/rides/search?' + new URLSearchParams({ from, to, date, seats: String(seats) }).toString());

export const getRide = (id) => api.get(`/rides/${encodeURIComponent(id)}`);
export const popularRoutes = () => api.get('/rides/popular');
export const myRides = () => api.get('/rides/mine');
export const publishRide = (body) => api.post('/rides', body);
export const updateRide = (id, body) => api.patch(`/rides/${encodeURIComponent(id)}`, body);
export const removeRide = (id) => api.del(`/rides/${encodeURIComponent(id)}`);
// Risk preview + allowed fare range for a draft ride: {km, durationMin, minFare, maxFare, risk}.
export const previewRide = (body) => api.post('/risk/preview', body);

export const listBookings = () => api.get('/bookings');
export const createBooking = (rideId, seats) => api.post('/bookings', { rideId, seats });
// action: cancel | start | checkins | missed | share | sos | complete | problems | rate
export const bookingAction = (id, action, body) => api.post(`/bookings/${encodeURIComponent(id)}/${action}`, body);
// Cancellation: what it would refund (paise), then do it.
export const getCancelQuote = (bookingId) => api.get(`/bookings/${encodeURIComponent(bookingId)}/cancellation-quote`);
export const getRideCancelQuote = (rideId) => api.get(`/rides/${encodeURIComponent(rideId)}/cancellation-quote`);
export const cancelRide = (rideId, reason) => api.post(`/rides/${encodeURIComponent(rideId)}/cancel`, { reason });
// The driver completes the whole ride; `noShow` lists booking ids of passengers who didn't turn up.
export const completeRide = (rideId, { noShow = [], note = '' } = {}) =>
  api.post(`/rides/${encodeURIComponent(rideId)}/complete`, { noShow, note });

// "Who can travel with me"
export const TRAVEL_WITH = [
  { value: 'anyone', label: 'Anyone' },
  { value: 'women', label: 'Women only', gender: 'F', hint: 'Only female drivers can offer women-only rides.' },
  { value: 'men', label: 'Men only', gender: 'M', hint: 'Only male drivers can offer men-only rides.' },
];
export const travelWithLabel = (v) => TRAVEL_WITH.find((t) => t.value === v)?.label || 'Anyone';
