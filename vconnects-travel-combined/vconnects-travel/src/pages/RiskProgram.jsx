import { useMemo, useState } from 'react';
import { CITIES } from '../data/cities.js';
import { DRIVERS, VEHICLES } from '../data/rides.js';
import { BANDS, scoreTrip } from '../lib/risk.js';
import { addDays, todayStr } from '../lib/format.js';
import RiskBreakdown from '../components/RiskBreakdown.jsx';
import Icon from '../components/Icon.jsx';

const FACTORS = [
  { icon: 'route', t: 'Route (25%)', d: 'An incident index for the corridor, the share of highway driving and any ghat or hill sections.' },
  { icon: 'moon', t: 'Time of day (20%)', d: 'Share of the drive falling between 10 pm and 5 am, plus a smaller weight for dusk and dawn.' },
  { icon: 'user', t: 'Driver (20%)', d: 'ID and licence verification, rating and trip history. New or unverified drivers score higher risk.' },
  { icon: 'cloud', t: 'Weather (15%)', d: 'Seasonal rain risk for the regions at both ends, such as the north-east monsoon on the east coast.' },
  { icon: 'clock', t: 'Drive length (10%)', d: 'Fatigue builds on long drives, so risk rises past about four hours.' },
  { icon: 'car', t: 'Vehicle (10%)', d: 'Age, airbags, ABS, dashcam, GPS tracker and first-aid kit.' },
];

const PROTECTIONS = [
  { icon: 'bell', t: 'Scheduled check-ins', d: 'Confirm you are okay at set points. A missed one alerts your trusted contacts.' },
  { icon: 'share', t: 'Live trip sharing', d: 'Send contacts a link with the route, driver and vehicle details.' },
  { icon: 'alert', t: 'One-tap SOS', d: 'Instantly shows helplines and your contacts, and flags the trip.' },
  { icon: 'shield', t: 'Verification', d: 'ID and licence badges are shown before you book, and feed straight into the score.' },
];

export default function RiskProgram() {
  const [from, setFrom] = useState('MAA');
  const [to, setTo] = useState('BLR');
  const [time, setTime] = useState('22:30');
  const [driverIdx, setDriverIdx] = useState(0);
  const [vehIdx, setVehIdx] = useState(0);

  const risk = useMemo(() => {
    if (from === to) return null;
    return scoreTrip({
      fromCode: from, toCode: to, depart: `${addDays(todayStr(), 1)}T${time}`,
      driver: DRIVERS[driverIdx], vehicle: VEHICLES[vehIdx],
    });
  }, [from, to, time, driverIdx, vehIdx]);

  return (
    <div className="container page">
      <h1 className="page-title">The VConnects risk program</h1>
      <p className="muted lead">Every ride carries a 0-100 trip risk score, where lower is safer, and every trip can be protected with check-ins, sharing and SOS.</p>

      <div className="bands">
        {BANDS.map((b, i) => (
          <div key={b.key} className={`band risk-${b.key}`}><strong>{b.label}</strong><span>{i === 0 ? '0' : BANDS[i - 1].max}-{Math.min(100, b.max - 1)}</span></div>
        ))}
      </div>

      <h2 className="sub">What goes into the score</h2>
      <div className="grid-3">
        {FACTORS.map((f) => <article key={f.t} className="feature"><span className="feature-icon"><Icon name={f.icon} size={22} /></span><h3>{f.t}</h3><p>{f.d}</p></article>)}
      </div>

      <h2 className="sub">Try the calculator</h2>
      <div className="calc">
        <div className="panel form-stack">
          <div className="row2">
            <label className="field"><span>From</span><select value={from} onChange={(e) => setFrom(e.target.value)}>{CITIES.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}</select></label>
            <label className="field"><span>To</span><select value={to} onChange={(e) => setTo(e.target.value)}>{CITIES.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}</select></label>
          </div>
          <label className="field"><span>Departure time</span><input type="time" value={time} onChange={(e) => setTime(e.target.value)} /></label>
          <label className="field"><span>Driver</span><select value={driverIdx} onChange={(e) => setDriverIdx(Number(e.target.value))}>{DRIVERS.map((d, i) => <option key={d.id} value={i}>{d.name}{d.verifiedId && d.verifiedLicense ? ' (verified)' : d.verifiedId || d.verifiedLicense ? ' (partly verified)' : ' (unverified)'}</option>)}</select></label>
          <label className="field"><span>Vehicle</span><select value={vehIdx} onChange={(e) => setVehIdx(Number(e.target.value))}>{VEHICLES.map((v, i) => <option key={v.model} value={i}>{v.model} ({v.year})</option>)}</select></label>
          <p className="fine">Try 22:30 against 10:00, or the Alto against the Creta, to see which factors move the score.</p>
        </div>
        <div className="panel">
          {risk ? <RiskBreakdown risk={risk} /> : <p className="muted">Choose two different cities.</p>}
        </div>
      </div>

      <h2 className="sub">Protection during the trip</h2>
      <div className="grid-4">
        {PROTECTIONS.map((f) => <article key={f.t} className="feature"><span className="feature-icon"><Icon name={f.icon} size={22} /></span><h3>{f.t}</h3><p>{f.d}</p></article>)}
      </div>
      <p className="fine disclaimer">Demo note: route incident data, weather and driver records are simulated to show how the program behaves. A production system would use real incident, weather and verification data sources.</p>
    </div>
  );
}
