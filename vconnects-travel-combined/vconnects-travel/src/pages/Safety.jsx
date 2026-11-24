import { Link } from '../router.jsx';
import Icon from '../components/Icon.jsx';

const HELPLINES = [
  { name: 'Emergency (all services)', num: '112' },
  { name: 'Women helpline', num: '1091' },
  { name: 'Highway / road accident help', num: '1033' },
];

const BEFORE = [
  'Check the driver’s ID, licence and vehicle badges on the ride page.',
  'Read the risk breakdown, especially for night or long-distance trips.',
  'Add at least one trusted contact in your profile.',
  'Confirm the vehicle number plate matches the booking before you get in.',
];
const DURING = [
  'Wear your seat belt and tap “I’m okay” at each check-in.',
  'Share the live trip link with a trusted contact.',
  'Sit where you are comfortable; you can ask to stop at a public place.',
  'Use SOS if you feel unsafe. It shows your contacts and helplines instantly.',
];
const AFTER = [
  'Rate the driver honestly. Ratings change future risk scores.',
  'Report anything that went wrong from the Contact page.',
];

function Checklist({ title, items }) {
  return (
    <article className="panel">
      <h3>{title}</h3>
      <ul className="check-list">
        {items.map((i) => <li key={i}><Icon name="check" size={16} /><span>{i}</span></li>)}
      </ul>
    </article>
  );
}

export default function Safety() {
  return (
    <div className="container page info-page">
      <span className="tag">Safety centre</span>
      <h1 className="page-title">Travel with a plan</h1>
      <p className="muted lead">Simple habits that make a shared trip safer, plus who to call if something goes wrong.</p>

      <div className="grid-3">
        <Checklist title="Before you go" items={BEFORE} />
        <Checklist title="During the trip" items={DURING} />
        <Checklist title="After you arrive" items={AFTER} />
      </div>

      <h2 className="sub">Helplines</h2>
      <div className="helplines">
        {HELPLINES.map((h) => (
          <a key={h.num} className="helpline" href={`tel:${h.num}`}>
            <Icon name="phone" size={20} />
            <span>{h.name}</span>
            <strong>{h.num}</strong>
          </a>
        ))}
      </div>

      <div className="cta-row">
        <Link to="/profile" className="btn btn-accent">Set up trusted contacts</Link>
        <Link to="/risk-program" className="btn btn-ghost">Risk program</Link>
      </div>
    </div>
  );
}
