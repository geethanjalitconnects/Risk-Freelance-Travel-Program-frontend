import { api } from './api.js';

// Razorpay Checkout. The browser only opens the payment window: the booking is confirmed by the
// server after it verifies the signature AND fetches the payment from Razorpay (or a webhook).
const SCRIPT = 'https://checkout.razorpay.com/v1/checkout.js';
let loading = null;

function loadScript() {
  if (window.Razorpay) return Promise.resolve();
  if (!loading) {
    loading = new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = SCRIPT;
      s.async = true;
      s.onload = () => resolve();
      s.onerror = () => { loading = null; reject(new Error("Couldn't load the payment window. Check your connection and try again.")); };
      document.head.appendChild(s);
    });
  }
  return loading;
}

export const getPriceQuote = (rideId, seats) => api.get(`/bookings/quote?rideId=${encodeURIComponent(rideId)}&seats=${seats}`);

// Pays for a held booking. Resolves with the updated booking once the server confirms it; rejects
// with { dismissed: true } if the passenger closes the window.
export async function payForBooking(bookingId) {
  const opts = await api.post(`/bookings/${encodeURIComponent(bookingId)}/pay`);
  await loadScript();
  return new Promise((resolve, reject) => {
    const rzp = new window.Razorpay({
      key: opts.keyId,
      order_id: opts.orderId,
      amount: opts.amount,
      currency: opts.currency,
      name: opts.name,
      description: opts.description,
      theme: { color: '#0b7c9c' },
      handler: async (res) => {
        try {
          resolve(await api.post(`/bookings/${encodeURIComponent(bookingId)}/payment/verify`, {
            razorpayOrderId: res.razorpay_order_id,
            razorpayPaymentId: res.razorpay_payment_id,
            razorpaySignature: res.razorpay_signature,
          }));
        } catch (e) {
          reject(e);
        }
      },
      modal: { ondismiss: () => reject(Object.assign(new Error('Payment not completed.'), { dismissed: true })) },
    });
    // A failed attempt keeps the window open so the passenger can retry; the hold still applies.
    rzp.open();
  });
}
