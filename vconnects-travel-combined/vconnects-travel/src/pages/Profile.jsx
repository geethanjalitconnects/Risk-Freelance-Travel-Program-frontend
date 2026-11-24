import { useEffect, useRef, useState } from 'react';
import { Link } from '../router.jsx';
import { GENDER_OPTIONS, addContact, loadMe, removeContact, signOut, updateMe, useAuth } from '../lib/auth.js';
import { STATUS_TEXT } from '../lib/verificationApi.js';
import Icon from '../components/Icon.jsx';
import { PayoutSummary } from './PayoutDetails.jsx';

function SignedOut() {
  return (
    <div className="container page narrow">
      <h1 className="page-title">Profile and safety setup</h1>
      <div className="panel form-stack">
        <p>Sign in with your mobile number to set up your profile, driver verification and trusted contacts.</p>
        <Link to="/login?next=/profile" className="btn btn-accent">Sign in or sign up</Link>
      </div>
    </div>
  );
}

export default function Profile() {
  const auth = useAuth();
  if (auth.status === 'loading') return <div className="container page narrow"><p className="muted">Loading your profile…</p></div>;
  if (auth.status === 'error') {
    return (
      <div className="container page narrow">
        <p className="callout warn">{auth.error}</p>
        <button className="btn btn-primary" onClick={loadMe}>Try again</button>
      </div>
    );
  }
  if (auth.status !== 'signed-in') return <SignedOut />;
  return <ProfileForm p={auth.user} />;
}

const VERIFICATION_TEXT = {
  not_submitted: 'Submit your vehicle number, driving licence and a government ID to publish rides.',
  pending: 'Your documents are being reviewed. You can publish rides once they are approved.',
  approved: 'You are a verified driver. Riders see a Verified badge on your rides.',
  rejected: 'Your verification was rejected. See the reason and resubmit.',
  resubmit_requested: 'Some documents need to be uploaded again. See which ones and re-upload them.',
  revoked: 'Your verification was revoked. See the reason and resubmit.',
};

function ProfileForm({ p }) {
  const [name, setName] = useState(p.name);
  const [email, setEmail] = useState(p.email || '');
  const [phone, setPhone] = useState(p.phone || '');
  const [saved, setSaved] = useState(false);
  const [aboutErr, setAboutErr] = useState('');
  const [c, setC] = useState({ name: '', phone: '', relation: '' });
  const [cErr, setCErr] = useState('');
  const [busy, setBusy] = useState('');
  const timer = useRef(null);

  useEffect(() => () => clearTimeout(timer.current), []);

  async function save(patch) {
    setAboutErr('');
    try {
      await updateMe(patch);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch (e) {
      setAboutErr(e.message);
    }
  }

  // Autosave the name shortly after typing stops, like the rest of this form.
  function onName(value) {
    setName(value);
    clearTimeout(timer.current);
    if (!value.trim()) return setAboutErr('Enter your name.');
    setAboutErr('');
    timer.current = setTimeout(() => save({ name: value }), 600);
  }

  async function add(e) {
    e.preventDefault();
    if (!c.name.trim()) return setCErr('Enter a name.');
    if (!/^\+?[0-9 ]{8,15}$/.test(c.phone.trim())) return setCErr('Enter a valid phone number (8-15 digits).');
    if (p.contacts.length >= 5) return setCErr('You can add up to 5 contacts.');
    setBusy('contact');
    try {
      await addContact({ name: c.name.trim(), phone: c.phone.trim(), relation: c.relation.trim() });
      setC({ name: '', phone: '', relation: '' });
      setCErr('');
    } catch (err) {
      setCErr(err.message);
    } finally {
      setBusy('');
    }
  }

  async function remove(id) {
    try {
      await removeContact(id);
    } catch (err) {
      setCErr(err.message);
    }
  }

  const status = p.driverVerification || 'not_submitted';
  const approved = status === 'approved';
  const level = [approved, p.contacts.length > 0].filter(Boolean).length;

  return (
    <div className="container page narrow">
      <h1 className="page-title">Profile and safety setup</h1>
      <div className="panel">
        <h3>Safety readiness <small className="muted">{level}/2</small></h3>
        <div className="progress"><span style={{ width: `${(level / 2) * 100}%` }} /></div>
        <ul className="ready">
          <li className={approved ? 'ok' : ''}>Driver verification approved (to publish rides)</li>
          <li className={p.contacts.length ? 'ok' : ''}>At least one trusted contact</li>
        </ul>
      </div>

      <div className="panel form-stack">
        <h3>About you {saved && <small className="ok-text">Saved</small>}</h3>
        <div className="row2">
          <label className="field"><span>Full name</span><input value={name} onChange={(e) => onName(e.target.value)} autoComplete="name" /></label>
          <label className="field"><span>Mobile number (for drivers / passengers and SOS)</span>
            <input value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" autoComplete="tel" placeholder="+91 98765 43210"
              onBlur={() => phone.trim() && phone.trim() !== (p.phone || '') && save({ phone: phone.trim() })} /></label>
        </div>
        {p.email ? (
          <label className="field"><span>Email (you sign in with this; review results are emailed here)</span>
            <input type="email" value={p.email} readOnly disabled /></label>
        ) : (
          <label className="field"><span>Add your email: you’ll sign in with it from now on</span>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" placeholder="you@example.com"
              onBlur={() => email.trim() && save({ email: email.trim() })} />
          </label>
        )}
        <label className="field"><span>Gender (enables women-only and men-only rides)</span>
          <select value={p.gender} disabled={Boolean(p.genderLocked)} onChange={(e) => save({ gender: e.target.value })}>
            {GENDER_OPTIONS.map((g) => <option key={g.value} value={g.value}>{g.label}</option>)}
          </select>
          {p.genderLocked && <small className="hint">{p.genderLocked}</small>}
        </label>
        {aboutErr && <p className="form-error" role="alert">{aboutErr}</p>}
      </div>

      <div className="panel form-stack">
        <h3>
          Driver verification <small className="muted">{STATUS_TEXT[status]}</small>{' '}
          {approved && <span className="trust ok"><Icon name="check" size={12} /> Verified</span>}
        </h3>
        <p className={['rejected', 'revoked', 'resubmit_requested'].includes(status) ? 'callout warn' : 'muted'}>{VERIFICATION_TEXT[status]}</p>
        <Link to="/verification" className={'btn ' + (approved ? 'btn-ghost' : 'btn-primary')}>
          {status === 'not_submitted' ? 'Submit documents' : approved ? 'View verification' : status === 'pending' ? 'View status' : status === 'resubmit_requested' ? 'Re-upload documents' : 'Fix and resubmit'}
        </Link>
      </div>

      {approved && (
        <div className="panel form-stack">
          <h3>Payout details</h3>
          <p className="muted">Where your ride earnings are paid: a bank account or UPI id.</p>
          <PayoutSummary userId={p.id} />
        </div>
      )}

      <div className="panel">
        <h3>Trusted contacts</h3>
        {p.contacts.length === 0 ? <p className="muted">No contacts yet.</p> : (
          <ul className="contacts">
            {p.contacts.map((x) => (
              <li key={x.id}>
                <div><b>{x.name}</b> <span className="muted">{x.relation}</span><br /><small>{x.phone}</small></div>
                <button className="icon-btn" aria-label={`Remove ${x.name}`} onClick={() => remove(x.id)}><Icon name="trash" /></button>
              </li>
            ))}
          </ul>
        )}
        <form onSubmit={add} className="form-stack" noValidate>
          <div className="row3">
            <label className="field"><span>Name</span><input value={c.name} onChange={(e) => setC({ ...c, name: e.target.value })} /></label>
            <label className="field"><span>Phone</span><input value={c.phone} onChange={(e) => setC({ ...c, phone: e.target.value })} inputMode="tel" /></label>
            <label className="field"><span>Relation</span><input value={c.relation} onChange={(e) => setC({ ...c, relation: e.target.value })} placeholder="Mother, friend…" /></label>
          </div>
          {cErr && <p className="form-error" role="alert">{cErr}</p>}
          <button className="btn btn-primary" type="submit" disabled={busy === 'contact'}>{busy === 'contact' ? 'Adding…' : 'Add contact'}</button>
        </form>
      </div>

      <div className="panel">
        <button className="btn btn-ghost" onClick={() => signOut()}>Sign out</button>
      </div>
    </div>
  );
}
