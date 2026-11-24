import { useState } from 'react';
import { Link } from '../router.jsx';
import { useAuth } from '../lib/auth.js';
import { useApi } from '../lib/useApi.js';
import { ACCOUNT_RE, IFSC_RE, PAYOUT_STATUS, UPI_RE, digitsOnly, getPayoutAccount, savePayoutAccount } from '../lib/payoutApi.js';
import Icon from '../components/Icon.jsx';

// Where drivers' earnings are paid: a bank account or a UPI id. The full account number is typed
// twice, sent once over HTTPS and never shown again (the server returns only the last 4 digits).
export default function PayoutDetails() {
  const auth = useAuth();
  if (auth.status === 'loading') return <div className="container page narrow"><p className="muted">Loading…</p></div>;
  if (auth.status !== 'signed-in') {
    return (
      <div className="container page narrow">
        <h1 className="page-title">Payout details</h1>
        <div className="panel form-stack">
          <p>Sign in to add the bank account or UPI id where your ride earnings are paid.</p>
          <Link to="/login?next=/payout-details" className="btn btn-accent">Sign in or sign up</Link>
        </div>
      </div>
    );
  }
  return <PayoutScreen userId={auth.user.id} />;
}

function PayoutScreen({ userId }) {
  const { data, error, loading, reload, setData } = useApi(getPayoutAccount, [userId]);
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState(false);

  if (loading && !data) return <div className="container page narrow"><p className="muted">Loading your payout details…</p></div>;
  if (error) {
    return (
      <div className="container page narrow">
        <p className="callout warn">{error.message}</p>
        <button className="btn btn-primary" onClick={reload}>Try again</button>
      </div>
    );
  }

  const { account, canEdit } = data;
  const showForm = canEdit && (editing || !account);

  return (
    <div className="container page narrow">
      <h1 className="page-title">Payout details</h1>
      <p className="muted lead">Your ride earnings are paid here after each trip is verified complete.</p>

      {!canEdit && (
        <div className="vbanner vb-info" role="status">
          <Icon name="shield" size={18} />
          <div className="vb-text"><strong>Available once you are a verified driver.</strong> Add payout details after your driver verification is approved.</div>
          <Link to="/verification" className="btn btn-primary btn-sm">Driver verification</Link>
        </div>
      )}

      {saved && !showForm && (
        <p className="callout" role="status"><Icon name="check" size={16} /> Saved. We'll verify these details before your first withdrawal.</p>
      )}

      {account && !showForm && (
        <div className="panel payout-card">
          <div className="payout-head">
            <div>
              <span className="payout-kind">{account.method === 'upi' ? 'UPI' : 'Bank account'}</span>
              <strong className="payout-dest">{account.display}</strong>
              <span className="muted">{account.holderName}{account.ifsc && ` · IFSC ${account.ifsc}`}</span>
            </div>
            <span className={'chip ' + (account.status === 'verified' ? 'chip-ok' : account.status === 'failed' ? 'chip-warn' : '')}>
              {PAYOUT_STATUS[account.status] || account.status}
            </span>
          </div>
          {account.status === 'failed' && (
            <p className="callout warn">We couldn't verify these details. Check them and save again.</p>
          )}
          {canEdit && <button className="btn btn-ghost" onClick={() => { setSaved(false); setEditing(true); }}>Edit payout details</button>}
          <p className="fine">Changing your details means they're verified again before your next withdrawal.</p>
        </div>
      )}

      {showForm && (
        <PayoutForm
          current={account}
          onCancel={account ? () => setEditing(false) : null}
          onSaved={(next) => { setData(next); setEditing(false); setSaved(true); window.scrollTo(0, 0); }}
        />
      )}

      <p className="fine"><Icon name="shield" size={12} /> Account numbers and UPI ids are stored encrypted. We only ever show the last 4 digits.</p>
    </div>
  );
}

const EMPTY = { holderName: '', bankName: '', accountNumber: '', confirmAccountNumber: '', ifsc: '', upiId: '' };

function validate(method, f) {
  const e = {};
  if (!/^[A-Za-z][A-Za-z .'-]{1,99}$/.test(f.holderName.trim())) e.holderName = 'Enter the name exactly as it appears on the account.';
  if (method === 'bank') {
    if (!f.bankName.trim()) e.bankName = "Enter your bank's name.";
    if (!ACCOUNT_RE.test(digitsOnly(f.accountNumber))) e.accountNumber = 'Enter a valid account number (9 to 18 digits).';
    else if (digitsOnly(f.confirmAccountNumber) !== digitsOnly(f.accountNumber)) e.confirmAccountNumber = "The account numbers don't match.";
    if (!IFSC_RE.test(f.ifsc.trim().toUpperCase())) e.ifsc = 'Enter a valid 11-character IFSC, like HDFC0001234.';
  } else if (!UPI_RE.test(f.upiId.trim())) {
    e.upiId = 'Enter a valid UPI id, like name@okbank.';
  }
  return e;
}

function PayoutForm({ current, onCancel, onSaved }) {
  const [method, setMethod] = useState(current?.method || 'bank');
  // Prefill only what the server returns; account numbers and UPI ids are always typed again.
  const [f, setF] = useState({ ...EMPTY, holderName: current?.holderName || '', bankName: current?.bankName || '', ifsc: current?.ifsc || '' });
  const [errors, setErrors] = useState({});
  const [formErr, setFormErr] = useState('');
  const [busy, setBusy] = useState(false);

  const set = (key) => (e) => {
    const value = key === 'ifsc' ? e.target.value.toUpperCase() : e.target.value;
    setF((prev) => ({ ...prev, [key]: value }));
    setErrors((prev) => ({ ...prev, [key]: '' }));
  };

  async function submit(e) {
    e.preventDefault();
    if (busy) return;
    const found = validate(method, f);
    setErrors(found);
    setFormErr('');
    if (Object.keys(found).length) return;
    setBusy(true);
    try {
      const body = method === 'bank'
        ? { method, holderName: f.holderName, bankName: f.bankName, accountNumber: f.accountNumber, confirmAccountNumber: f.confirmAccountNumber, ifsc: f.ifsc }
        : { method, holderName: f.holderName, upiId: f.upiId };
      const next = await savePayoutAccount(body);
      setF(EMPTY); // don't keep the account number in memory longer than needed
      onSaved(next);
    } catch (err) {
      const fields = {};
      for (const key of Object.keys(EMPTY)) if (err.field?.(key)) fields[key] = err.field(key);
      setErrors(fields);
      if (!Object.keys(fields).length) setFormErr(err.message);
    } finally {
      setBusy(false);
    }
  }

  const field = (key, label, props = {}) => (
    <label className="field">
      <span>{label}</span>
      <input value={f[key]} onChange={set(key)} aria-invalid={Boolean(errors[key])} {...props} />
      {errors[key] && <small className="field-error">{errors[key]}</small>}
    </label>
  );

  return (
    <form className="panel form-stack" onSubmit={submit} noValidate>
      <h3>{current ? 'Edit payout details' : 'Add payout details'}</h3>
      <div className="seg" role="group" aria-label="Payout method">
        <button type="button" className={method === 'bank' ? 'on' : ''} aria-pressed={method === 'bank'} onClick={() => setMethod('bank')}>Bank account</button>
        <button type="button" className={method === 'upi' ? 'on' : ''} aria-pressed={method === 'upi'} onClick={() => setMethod('upi')}>UPI</button>
      </div>

      {field('holderName', 'Account holder name', { autoComplete: 'name', maxLength: 100 })}

      {method === 'bank' ? (
        <>
          {field('bankName', 'Bank name', { maxLength: 100, placeholder: 'HDFC Bank' })}
          <div className="row2">
            {field('accountNumber', 'Account number', { inputMode: 'numeric', autoComplete: 'off', maxLength: 22 })}
            {field('confirmAccountNumber', 'Confirm account number', { inputMode: 'numeric', autoComplete: 'off', maxLength: 22, onPaste: (e) => e.preventDefault() })}
          </div>
          {field('ifsc', 'IFSC', { autoComplete: 'off', maxLength: 11, placeholder: 'HDFC0001234' })}
          <p className="fine">The IFSC is on your cheque book or passbook: 4 letters, a zero, then 6 letters or digits.</p>
        </>
      ) : (
        field('upiId', 'UPI id', { autoComplete: 'off', maxLength: 300, placeholder: 'name@okbank', inputMode: 'email' })
      )}

      {formErr && <p className="form-error" role="alert">{formErr}</p>}
      <div className="live-actions">
        <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save payout details'}</button>
        {onCancel && <button className="btn btn-ghost" type="button" onClick={onCancel} disabled={busy}>Cancel</button>}
      </div>
    </form>
  );
}

// A one-line summary + link, for Profile and the verification page.
export function PayoutSummary({ userId, prompt = false }) {
  const { data } = useApi(getPayoutAccount, [userId]);
  if (!data?.canEdit) return null;
  const a = data.account;
  if (!a) {
    return (
      <div className={prompt ? 'vbanner vb-info' : 'payout-line'} role="status">
        {prompt && <Icon name="bell" size={18} />}
        <div className="vb-text"><strong>Next step: add your payout details.</strong> Tell us where to pay your ride earnings.</div>
        <Link to="/payout-details" className="btn btn-primary btn-sm">Add payout details</Link>
      </div>
    );
  }
  return (
    <div className="payout-line">
      <span><b>{a.display}</b> <span className="muted">· {PAYOUT_STATUS[a.status] || a.status}</span></span>
      <Link to="/payout-details" className="btn btn-ghost btn-sm">Edit</Link>
    </div>
  );
}
