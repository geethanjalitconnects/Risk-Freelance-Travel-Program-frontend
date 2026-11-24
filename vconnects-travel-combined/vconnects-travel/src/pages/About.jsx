import { Link } from '../router.jsx';
import Icon from '../components/Icon.jsx';

const VALUES = [
  { icon: 'shield', t: 'Safety first', d: 'Every ride carries a trip risk score, and every driver is checked before they can offer a seat.' },
  { icon: 'user', t: 'People, not strangers', d: 'Profiles, ratings and trusted contacts mean you know who you are travelling with.' },
  { icon: 'route', t: 'Shared roads', d: 'Filling empty seats cuts costs and keeps cars off the road for the same journey.' },
];

export default function About() {
  return (
    <div className="container page info-page">
      <span className="tag">About VConnects</span>
      <h1 className="page-title">Carpooling built around <span className="grad-text">how safe the trip is</span>.</h1>
      <p className="muted lead">
        Most ride-sharing apps compare price and departure time. VConnects adds the thing people actually worry about:
        how risky is this journey, and who is driving it?
      </p>

      <div className="grid-3">
        {VALUES.map((v) => (
          <article key={v.t} className="feature">
            <span className="feature-icon"><Icon name={v.icon} size={22} /></span>
            <h3>{v.t}</h3>
            <p>{v.d}</p>
          </article>
        ))}
      </div>

      <h2 className="sub">What we do</h2>
      <div className="panel prose">
        <p>
          VConnects connects drivers who have empty seats with passengers going the same way. Before you book, you see a
          0&ndash;100 risk score built from the route, time of day, driver, weather, drive length and vehicle. During the
          trip you get scheduled check-ins, live trip sharing with your trusted contacts, and a one-tap SOS.
        </p>
        <p>
          Drivers verify their ID, licence and vehicle. Passengers can add up to five trusted contacts. Women-only and
          men-only rides are available where the driver offers them.
        </p>
      </div>

      <div className="cta-row">
        <Link to="/" className="btn btn-accent">Find a ride <Icon name="arrow" size={16} /></Link>
        <Link to="/risk-program" className="btn btn-ghost">How the score works</Link>
      </div>
    </div>
  );
}
