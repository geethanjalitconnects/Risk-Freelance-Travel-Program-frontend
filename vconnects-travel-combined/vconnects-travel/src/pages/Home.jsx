import { useRef } from 'react';
import { Link, navigate, scrollToId } from '../router.jsx';
import SearchForm from '../components/SearchForm.jsx';
import Icon from '../components/Icon.jsx';
import DrivingCar from '../components/DrivingCar.jsx';
import { addDays, todayStr } from '../lib/format.js';
import { popularRoutes } from '../lib/ridesApi.js';
import { useApi } from '../lib/useApi.js';

const SECTIONS = [
  { tag: 'Before the road', title: 'Know the risk.\nChoose your ride.', text: 'Every ride is scored and every driver is checked, so you know what you are getting into before you book.', features: [
    { icon: 'shield', title: 'Trip risk score on every ride', text: 'Route, time of day, driver, weather, drive length and vehicle are blended into one 0–100 score before you book.', chip: 'Trip risk 28 · Low' },
    { icon: 'check', title: 'Verified drivers', text: 'Every driver’s licence, ID and vehicle are checked by our team before they can offer rides.', chip: 'Licence · ID · Vehicle' },
  ] },
  { tag: 'On the trip', title: 'Looked after.\nEvery mile.', text: 'Check-ins and one-tap SOS stay with you from pickup to drop-off, with your trusted contacts in the loop.', features: [
    { icon: 'bell', title: 'Live check-ins', text: 'Scheduled check-ins during the trip. Miss one and your trusted contacts would be alerted.', chip: 'Trusted contacts alerted' },
    { icon: 'alert', title: 'One-tap SOS', text: 'Your emergency contacts, helplines and live trip details in one place.', chip: 'Helplines · live trip' },
  ] },
];

// Busiest upcoming routes, from real rides (hidden until there are some).
function Popular() {
  const { data } = useApi(popularRoutes, []);
  if (!data?.length) return null;
  return (
    <div className="popular"><span>Popular:</span>{data.map((r) => (
      <button type="button" key={r.from.area.code + r.to.area.code} className="pill"
        onClick={() => navigate('/search', {
          from: r.from.placeId, fromLabel: r.from.area.name, to: r.to.placeId, toLabel: r.to.area.name,
          date: addDays(todayStr(), 1), seats: 1,
        })}>
        {r.from.area.name} <Icon name="arrow" size={12} /> {r.to.area.name}
      </button>
    ))}</div>
  );
}

const FIRST_INPUT = '.sf-field input';

export default function Home() {
  const journeyRef = useRef(null);
  const goTo = (id) => (e) => { e.preventDefault(); scrollToId(id, FIRST_INPUT); };
  return (
    <>
      <div className="home-journey" ref={journeyRef}>
        <div className="journey-car-track"><DrivingCar journeyRef={journeyRef} /></div>
        <section className="journey-intro" id="hero" aria-label="VConnects carpooling">
          <div className="container">
            <div className="journey-copy">
              <span className="tag">VConnects · Safer carpooling</span>
              <h1>Risk<br /><span className="grad-text">Freelance Travel Program</span></h1>
              <p>VConnects matches you with verified drivers heading your way, and scores every trip so you can pick the safest option, not just the cheapest.</p>
              <a href="#/" onClick={goTo('search-form')} className="btn btn-accent journey-find">Find a ride <Icon name="arrow" size={16} /></a>
            </div>
            <div className="journey-search" id="search-form"><SearchForm /><Popular /></div>
          </div>
        </section>
        {SECTIONS.map((section, index) => (
          <section className="journey-section" key={section.tag}>
            <div className="container">
              <div className="journey-copy">
                <span className="journey-number">0{index + 1}</span>
                <span className="tag">{section.tag}</span>
                <h2>{section.title.split('\n').map((line) => <span key={line}>{line}<br /></span>)}</h2>
                <p>{section.text}</p>
                <div className="journey-features">
                  {section.features.map((feature) => <article className="journey-feature" key={feature.title}>
                    <span className="journey-feature-icon"><Icon name={feature.icon} size={23} /></span>
                    <div><h3>{feature.title}</h3><p>{feature.text}</p><span className="journey-feature-chip">{feature.chip}</span></div>
                  </article>)}
                </div>
              </div>
            </div>
          </section>
        ))}
        <section className="journey-section journey-ready">
          <div className="container"><div className="journey-copy">
            <span className="tag">Ready when you are</span>
            <h2>Share the road.<br /><span className="grad-text">Split the cost.</span></h2>
            <div className="cta-row">
              <a href="#/" onClick={goTo('find')} className="btn btn-accent">Find a ride <Icon name="arrow" size={16} /></a>
              <Link to="/publish" className="btn btn-ghost">Offer a ride</Link>
            </div>
          </div></div>
        </section>
      </div>
      <section className="home-find" id="find">
        <div className="container">
          <span className="tag">Plug in and go</span>
          <div className="home-find-heading"><h2>Your seat is<br />already waiting.</h2><p>Pick your cities, date and seats. Compare price, departure time and trip risk side by side.</p></div>
          <SearchForm />
          <Link to="/publish" className="home-offer"><span>Heading somewhere? Offer a ride and share the cost</span><Icon name="arrow" size={24} /></Link>
        </div>
      </section>
    </>
  );
}
