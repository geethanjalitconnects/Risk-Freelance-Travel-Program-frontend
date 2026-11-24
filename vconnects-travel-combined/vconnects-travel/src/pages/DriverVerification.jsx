import { useState } from 'react';
import { Link } from '../router.jsx';
import { loadMe, useAuth } from '../lib/auth.js';
import { useApi } from '../lib/useApi.js';
import { ACCEPT, ID_TYPES, STATUS_TEXT, fileError, fmtPlate, getVerification, submitVerification, uploadDocument } from '../lib/verificationApi.js';
import { fmtDateTime } from '../lib/format.js';
import Icon from '../components/Icon.jsx';
import VerificationBanner from '../components/VerificationBanner.jsx';
import { PayoutSummary } from './PayoutDetails.jsx';

const FILES = [
  { key: 'licenceFront', label: 'Driving licence (front)', required: true },
  { key: 'licenceBack', label: 'Driving licence (back)', required: true },
  { key: 'idFront', label: 'Government ID (front)', required: true },
  { key: 'idBack', label: 'Government ID (back, optional)', required: false, hint: 'Needed for a Voter ID. PAN, the passport photo page and the masked Aadhaar are one side.' },
];

export default function DriverVerification() {
  const auth = useAuth();
  if (auth.status === 'loading') return <div className="container page narrow"><p className="muted">Loading…</p></div>;
  if (auth.status !== 'signed-in') {
    return (
      <div className="container page narrow">
        <h1 className="page-title">Driver verification</h1>
        <div className="panel form-stack">
          <p>Sign in to submit your documents and publish rides.</p>
          <Link to="/login?next=/verification" className="btn btn-accent">Sign in or sign up</Link>
        </div>
      </div>
    );
  }
  return <VerificationScreen userId={auth.user.id} />;
}

function VerificationScreen({ userId }) {
  const { data: v, error, loading, reload, setData } = useApi(getVerification, [userId]);
  const [editing, setEditing] = useState(false);

  if (loading && !v) return <div className="container page narrow"><p className="muted">Loading your verification…</p></div>;
  if (error) {
    return (
      <div className="container page narrow">
        <p className="callout warn">{error.message}</p>
        <button className="btn btn-primary" onClick={reload}>Try again</button>
      </div>
    );
  }

  // Rejected / revoked: submit everything again. Re-upload requested: replace only the rejected documents.
  const showForm = editing || v.status === 'not_submitted' || v.status === 'rejected' || v.status === 'revoked';
  const toDocuments = () => document.getElementById('your-documents')?.scrollIntoView({ behavior: 'smooth' });
  const toForm = () => (v.status === 'resubmit_requested' ? toDocuments() : document.getElementById('submit-form')?.scrollIntoView({ behavior: 'smooth' }));
  const done = (next) => {
    setData(next);
    setEditing(false);
    loadMe(); // refresh the status shown in Profile
    window.scrollTo(0, 0);
  };

  return (
    <div className="container page narrow">
      <h1 className="page-title">Driver verification</h1>
      <p className="muted lead">To publish rides, our team checks your driving licence, a government ID and your vehicle number.</p>

      <VerificationBanner v={v} onReupload={toForm} />
      {v.status === 'approved' && <PayoutSummary userId={userId} prompt />}
      <StatusPanel v={v} />

      {!showForm && ['pending', 'approved', 'resubmit_requested'].includes(v.status) && (
        <DocumentList v={v} onDone={done} />
      )}

      {!showForm && v.status === 'pending' && (
        <p className="fine">Need to change your vehicle number or ID type? <button className="btn btn-ghost btn-sm" onClick={() => setEditing(true)}>Resubmit everything</button></p>
      )}
      {!showForm && v.status === 'approved' && (
        <div className="panel">
          <p>Changed your vehicle? Resubmitting sends your account back to review, and your rides are hidden from search until
            it is approved again.</p>
          <button className="btn btn-ghost" onClick={() => setEditing(true)}>Update vehicle or documents</button>
        </div>
      )}

      {showForm && <div id="submit-form"><SubmitForm current={v} onDone={done} onCancel={editing ? () => setEditing(false) : null} /></div>}

      <p className="fine">
        <Icon name="shield" size={14} /> Your documents are encrypted and only our verification team can open them. Riders
        see a Verified badge once you are approved. Passengers who book your ride also see your vehicle number.
      </p>
    </div>
  );
}

function StatusPanel({ v }) {
  if (v.status === 'not_submitted') return null;
  return (
    <div className="panel">
      <h3>
        Status: {STATUS_TEXT[v.status]}{' '}
        {v.status === 'approved' && <span className="trust ok"><Icon name="check" size={12} /> Verified</span>}
      </h3>
      <p className="muted">
        {v.email && <>Decisions are emailed to {v.email} · </>}
        Vehicle {fmtPlate(v.vehicleNumber)}
        {v.submittedAt && <> · submitted {fmtDateTime(v.submittedAt)}</>}
        {v.reviewedAt && v.status !== 'pending' && <> · reviewed {fmtDateTime(v.reviewedAt)}</>}
      </p>
    </div>
  );
}

const DOC_STATUS = { pending: 'In review', approved: 'Approved', rejected: 'Not accepted' };

// Each document with its review result. A single document can be replaced; for an approved driver
// that sends the account back to review (the server enforces this too).
function DocumentList({ v, onDone }) {
  const [open, setOpen] = useState(null); // kind being replaced
  const docs = [...v.documentReviews];
  if (!docs.some((d) => d.kind === 'id_back')) docs.push({ kind: 'id_back', label: 'Government ID (back)', status: null, optional: true });
  const needed = docs.filter((d) => d.status === 'rejected').length;

  return (
    <div className="panel form-stack" id="your-documents">
      <h3>Your documents</h3>
      {v.status === 'resubmit_requested' && (
        <p className="callout warn">Re-upload the {needed === 1 ? 'document' : `${needed} documents`} marked “Not accepted”. Your
          submission goes back to review once all of them are replaced.</p>
      )}
      {v.status === 'approved' && (
        <p className="fine">Replacing a document sends your account back to review. You can't post or edit rides until it is approved again.</p>
      )}
      <ul className="doc-list">
        {docs.map((d) => (
          <li key={d.kind} className={'doc-row' + (d.status === 'rejected' ? ' doc-bad' : '')}>
            <div className="doc-main">
              <strong>{d.label}</strong>
              {d.status
                ? <span className={'doc-chip dc-' + d.status}>{DOC_STATUS[d.status]}</span>
                : <span className="doc-chip">Optional, not uploaded</span>}
              {d.rejectionReason && <span className="doc-reason">{d.rejectionReason}</span>}
            </div>
            {open !== d.kind && (
              <button className={'btn btn-sm ' + (d.status === 'rejected' ? 'btn-accent' : 'btn-ghost')} onClick={() => setOpen(d.kind)}>
                {d.status === 'rejected' ? 'Re-upload' : d.status ? 'Replace' : 'Upload'}
              </button>
            )}
            {open === d.kind && <ReplaceDoc v={v} kind={d.kind} onCancel={() => setOpen(null)} onDone={(next) => { setOpen(null); onDone(next); }} />}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ReplaceDoc({ v, kind, onCancel, onDone }) {
  const [file, setFile] = useState(null);
  const [masked, setMasked] = useState(false);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const aadhaarId = v.idType === 'aadhaar' && kind.startsWith('id_');

  async function send(e) {
    e.preventDefault();
    const msg = fileError(file, true) || (aadhaarId && !masked ? 'Confirm that you are uploading the masked Aadhaar.' : '');
    if (msg) return setErr(msg);
    const form = new FormData();
    form.append('file', file);
    if (aadhaarId) form.append('aadhaarMasked', 'true');
    setBusy(true);
    try {
      onDone(await uploadDocument(kind, form));
    } catch (ex) {
      setErr(ex.field?.('file') || ex.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="doc-upload" onSubmit={send} noValidate>
      <input type="file" accept={ACCEPT} onChange={(e) => { setFile(e.target.files[0] || null); setErr(''); }} aria-label="Choose a file" />
      {aadhaarId && (
        <label className="check"><input type="checkbox" checked={masked} onChange={(e) => setMasked(e.target.checked)} /> This is the masked Aadhaar.</label>
      )}
      {err && <small className="field-error" role="alert">{err}</small>}
      <div className="row-inline">
        <button className="btn btn-accent btn-sm" type="submit" disabled={busy}>{busy ? 'Uploading…' : 'Upload'}</button>
        <button className="btn btn-ghost btn-sm" type="button" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

function SubmitForm({ current, onDone, onCancel }) {
  const [email, setEmail] = useState(current.email || '');
  const [vehicle, setVehicle] = useState(current.vehicleNumber ? fmtPlate(current.vehicleNumber) : '');
  const [idType, setIdType] = useState(current.idType || 'pan');
  const [masked, setMasked] = useState(false);
  const [files, setFiles] = useState({});
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    const err = {};
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) err.email = 'Enter your email address. We email you when your documents are reviewed.';
    if (!/^[A-Za-z0-9 .-]{6,16}$/.test(vehicle.trim())) err.vehicleNumber = 'Enter a valid vehicle registration number, e.g. TN 09 AB 1234.';
    if (idType === 'aadhaar' && !masked) err.aadhaarMasked = 'Confirm that you are uploading the masked Aadhaar.';
    for (const f of FILES) {
      const msg = fileError(files[f.key], f.required);
      if (msg) err[f.key] = msg;
    }
    setErrors(err);
    if (Object.keys(err).length) return;

    const form = new FormData();
    form.append('email', email.trim());
    form.append('vehicleNumber', vehicle.trim());
    form.append('idType', idType);
    form.append('aadhaarMasked', idType === 'aadhaar' && masked ? 'true' : 'false');
    for (const f of FILES) if (files[f.key]) form.append(f.key, files[f.key]);

    setBusy(true);
    try {
      onDone(await submitVerification(form));
    } catch (ex) {
      const server = {};
      for (const [k, val] of Object.entries(ex.data || {})) server[k] = Array.isArray(val) ? val[0] : String(val);
      setErrors(Object.keys(server).length && !server.detail ? server : { form: ex.message });
    } finally {
      setBusy(false);
    }
  }

  const Err = ({ k }) => (errors[k] ? <small className="field-error" role="alert">{errors[k]}</small> : null);

  return (
    <form className="panel form-stack" onSubmit={submit} noValidate>
      <h3>{current.status === 'not_submitted' ? 'Submit your documents' : 'Resubmit your documents'}</h3>
      {current.status !== 'not_submitted' && <p className="fine">Resubmitting replaces the documents you sent before.</p>}

      <label className="field"><span>Email (we email you the review result)</span>
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" autoComplete="email" />
        <Err k="email" /></label>

      <label className="field"><span>Vehicle registration number</span>
        <input value={vehicle} onChange={(e) => setVehicle(e.target.value.toUpperCase())} placeholder="TN 09 AB 1234" autoComplete="off" />
        <Err k="vehicleNumber" /></label>

      <label className="field"><span>Government ID type</span>
        <select value={idType} onChange={(e) => setIdType(e.target.value)}>
          {ID_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
        </select>
        <Err k="idType" /></label>

      {idType === 'aadhaar' && (
        <div className="callout">
          <p>Upload only the <b>masked Aadhaar</b>, which shows just the last 4 digits of your Aadhaar number. Download it from the
            official UIDAI site: <a href="https://myaadhaar.uidai.gov.in/" target="_blank" rel="noopener noreferrer">myaadhaar.uidai.gov.in</a>{' '}
            (choose “Download Aadhaar”, then “masked Aadhaar”). Unmasked copies are rejected and deleted.</p>
          <label className="check">
            <input type="checkbox" checked={masked} onChange={(e) => setMasked(e.target.checked)} /> This is the masked Aadhaar: only the last 4 digits are visible.
          </label>
          <Err k="aadhaarMasked" />
        </div>
      )}

      {FILES.map((f) => (
        <label key={f.key} className="field"><span>{f.label}</span>
          <input type="file" accept={ACCEPT} onChange={(e) => setFiles({ ...files, [f.key]: e.target.files[0] || null })} />
          {f.hint && <small className="hint">{f.hint}</small>}
          <Err k={f.key} /></label>
      ))}
      <p className="fine">JPG, PNG or PDF, up to 5 MB each.</p>

      {errors.form && <p className="form-error" role="alert">{errors.form}</p>}
      <div className="row2">
        <button className="btn btn-accent" type="submit" disabled={busy}>{busy ? 'Uploading…' : 'Submit for review'}</button>
        {onCancel && <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancel</button>}
      </div>
    </form>
  );
}
