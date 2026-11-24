import { Link } from '../router.jsx';
import Icon from '../components/Icon.jsx';

const PASSENGER = [
  { t: 'Search', d: 'Pick your cities, date and number of seats. Sort by earliest, cheapest or safest.' },
  { t: 'Compare the risk', d: 'Open a ride to see the full risk breakdown, driver trust badges and vehicle safety features.' },
  { t: 'Book a seat', d: 'Reserve the seats you need. You can cancel before the trip starts.' },
  { t: 'Travel protected', d: 'Use check-ins, share your live trip and keep SOS one tap away until you arrive.' },
  { t: 'Rate the driver', d: 'After arrival, rate the trip. Ratings feed back into the driver score.' },
];

const DRIVER = [
  { t: 'Verify', d: 'Add your ID, licence and vehicle details from your profile.' },
  { t: 'Publish a ride', d: 'Enter route, time, seats and who can travel with you. You see a live risk preview and the allowed fare range.' },
  { t: 'Manage bookings', d: 'See who has booked from My trips, edit the ride before departure, or remove it.' },
  { t: 'Drive and complete', d: 'Passengers check in along the way. Finish the trip to build your rating.' },
];

function Steps({ items }) {
  return (
    <ol className="steps-list">
      {items.map((s, i) => (
        <li key={s.t} className="step">
          <span className="step-num">{i + 1}</span>
          <div><h3>{s.t}</h3><p>{s.d}</p></div>
        </li>
      ))}
    </ol>
  );
}

export default function HowItWorks() {
  return (
    <div className="container page info-page">
      <span className="tag">How it works</span>
      <h1 className="page-title">From search to safe arrival</h1>
      <p className="muted lead">Whether you are taking a seat or offering one, here is what to expect.</p>

      <h2 className="sub">As a passenger</h2>
      <Steps items={PASSENGER} />

      <h2 className="sub">As a driver</h2>
      <Steps items={DRIVER} />

      <div className="cta-row">
        <Link to="/" className="btn btn-accent">Find a ride <Icon name="arrow" size={16} /></Link>
        <Link to="/publish" className="btn btn-ghost">Offer a ride</Link>
      </div>
    </div>
  );
}
