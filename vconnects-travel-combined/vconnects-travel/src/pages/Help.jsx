import { Link } from '../router.jsx';

const FAQ = [
  { q: 'How is the trip risk score calculated?', a: 'A 0–100 score where lower is safer: route 25%, time of day 20%, driver 20%, weather 15%, drive length 10% and vehicle 10%. Bands are Low (under 30), Moderate (30–49), Elevated (50–69) and High (70+).' },
  { q: 'How do I sign in?', a: 'Enter your mobile number and the one-time code we send you. There is no password.' },
  { q: 'How do I book a seat?', a: 'Search for your route, open a ride, choose the number of seats and confirm. Your booking appears under My trips.' },
  { q: 'Can I cancel a booking?', a: 'Yes. Open My trips and cancel while the booking is still confirmed, before the trip starts.' },
  { q: 'How do I offer a ride?', a: 'Choose Publish a ride, enter the route, time, seats and who can travel with you. Complete driver verification in your profile first.' },
  { q: 'What happens if I miss a check-in?', a: 'The missed check-in is logged on the trip and your trusted contacts are alerted.' },
  { q: 'What do women-only and men-only rides mean?', a: 'Only drivers of the matching gender can offer them, and only matching passengers can book them. Set your gender in your profile.' },
  { q: 'Are payments handled in the app?', a: 'No. Fares are shown so you can agree the cost with the driver; the app does not take payments.' },
  { q: 'How do I add trusted contacts?', a: 'Go to Profile and add up to five people. They are the ones alerted by missed check-ins and SOS.' },
];

export default function Help() {
  return (
    <div className="container page info-page narrow">
      <span className="tag">Help centre</span>
      <h1 className="page-title">Frequently asked questions</h1>
      <p className="muted lead">Can’t find your answer? <Link to="/contact">Contact us</Link>.</p>
      <div className="faq">
        {FAQ.map((f) => (
          <details key={f.q} className="faq-item">
            <summary>{f.q}</summary>
            <p>{f.a}</p>
          </details>
        ))}
      </div>
    </div>
  );
}
