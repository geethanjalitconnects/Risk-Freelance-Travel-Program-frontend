// /admin/review/:userId. Every review decision happens here; the server applies the rules,
// writes the audit log and sends the emails.
import { useEffect, useState } from 'react';
import { useApi } from '../../lib/useApi.js';
import {
  STATUS_LABEL, approveDocument, approveProfile, fmtWhen, getDocumentBlob, getReview, rejectDocument, rejectProfile,
  requestResubmit, retryEmail, revokeProfile,
} from '../adminApi.js';

const DOC_LABEL = { pending: 'To review', approved: 'Approved', rejected: 'Rejected' };
const EMAIL_LABEL = { queued: 'Sending…', sent: 'Sent', failed: 'Email failed', no_address: 'No email address' };

export default function Review({ userId, admin }) {
  const { data, error, loading, reload, setData } = useApi(() => getReview(userId), [userId]);
  const [busy, setBusy] = useState('');
  const [actionError, setActionError] = useState('');

  // Run a decision; the response is the refreshed review page.
  async function act(key, fn) {
    setBusy(key);
    setActionError('');
    try {
      setData(await fn());
      return true;
    } catch (ex) {
      setActionError(ex.message);
      return false;
    } finally {
      setBusy('');
    }
  }

  if (loading && !data) return <p className="adm-muted">Loading…</p>;
  if (error) {
    return (
      <div className="adm-card">
        <p className="callout warn">{error.status === 404 ? 'This user has no driver verification.' : error.message}</p>
        <a href="#/admin/queue" className="btn btn-ghost">Back to the queue</a>
      </div>
    );
  }

  const { user, verification: v, documents, emails, history } = data;
  const pending = v.status === 'pending';
  const canReview = admin.canReview;

  return (
    <section className="adm-review">
      <a href="#/admin/queue" className="adm-back">← Review queue</a>
      <div className="adm-head">
        <div>
          <h1>{user.name || '(no name)'}</h1>
          <p className="adm-muted">{user.phone} · {user.email || 'no email on file'} · {user.gender} · member since {user.memberSince}{!user.isActive && ' · deactivated'}</p>
        </div>
        <span className={'adm-status big s-' + v.status}>{STATUS_LABEL[v.status]}</span>
      </div>

      {actionError && <p className="callout warn" role="alert">{actionError}</p>}

      <div className="adm-grid">
        <div>
          <div className="adm-card">
            <h2>Submission</h2>
            <dl className="adm-dl">
              <dt>Vehicle</dt><dd className="mono">{v.vehicleNumber}</dd>
              <dt>Government ID</dt><dd>{v.idTypeLabel}</dd>
              <dt>Submitted</dt><dd>{fmtWhen(v.submittedAt)}</dd>
              {v.reviewedAt && <><dt>Reviewed</dt><dd>{fmtWhen(v.reviewedAt)}{v.reviewedBy && ` by ${v.reviewedBy.name}`}</dd></>}
              {v.rejectionReason && <><dt>Reason</dt><dd className="pre-line">{v.rejectionReason}</dd></>}
            </dl>
            {v.isAadhaar && (
              <p className="callout warn">Aadhaar: check that only the last 4 digits are visible. If the copy isn't masked, reject the
                profile and tick “not masked”; the ID documents are then deleted at once.</p>
            )}
            {data.missingDocuments.length > 0 && <p className="callout warn">Missing: {data.missingDocuments.join(', ')}</p>}
          </div>

          <h2 className="adm-h2">Documents</h2>
          {documents.length === 0 && <div className="adm-card"><p className="adm-muted">No documents on file.</p></div>}
          {documents.map((d) => (
            <DocumentCard key={d.id} d={d} userId={userId} canDecide={pending && canReview} canOpen={admin.canOpenDocuments} busy={busy} act={act} />
          ))}
        </div>

        <aside>
          {canReview && <Decisions data={data} userId={userId} busy={busy} act={act} />}
          <Emails emails={emails} canRetry={canReview} busy={busy} act={act} />
          <div className="adm-card">
            <h2>History</h2>
            {history.length === 0 ? <p className="adm-muted">No changes yet.</p> : (
              <ol className="adm-history">
                {history.map((h, i) => (
                  <li key={i}>
                    <span className="small adm-muted">{fmtWhen(h.at)}</span>
                    <div>{STATUS_LABEL[h.from]} → <strong>{STATUS_LABEL[h.to]}</strong>{h.actor && <> by {h.actor.name}</>}</div>
                    {h.reason && <div className="small pre-line">{h.reason}</div>}
                  </li>
                ))}
              </ol>
            )}
          </div>
          <button className="btn btn-ghost btn-sm" onClick={reload}>Refresh</button>
        </aside>
      </div>
    </section>
  );
}

function DocumentCard({ d, userId, canDecide, canOpen, busy, act }) {
  const [url, setUrl] = useState(null);
  const [viewError, setViewError] = useState('');
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState('');
  const [reasonError, setReasonError] = useState('');

  useEffect(() => () => url && URL.revokeObjectURL(url), [url]);

  async function toggleView() {
    if (url) return setUrl(null);
    setViewError('');
    try {
      setUrl(URL.createObjectURL(await getDocumentBlob(d.id)));
    } catch (ex) {
      setViewError(ex.message);
    }
  }

  async function reject(e) {
    e.preventDefault();
    if (!reason.trim()) return setReasonError('Enter a reason. The driver sees it.');
    setReasonError('');
    if (await act('doc-reject-' + d.id, () => rejectDocument(userId, d.id, reason.trim()))) {
      setRejecting(false);
      setReason('');
    }
  }

  return (
    <div className={'adm-card adm-doc d-' + d.status}>
      <div className="adm-doc-head">
        <div>
          <strong>{d.label}</strong>{!d.required && <span className="adm-muted small"> (optional)</span>}
          <div className="adm-muted small">{d.contentType.split('/')[1].toUpperCase()}, {d.sizeKb} KB · uploaded {fmtWhen(d.uploadedAt)}</div>
        </div>
        <span className={'adm-doc-status ds-' + d.status}>{DOC_LABEL[d.status]}</span>
      </div>
      {d.rejectionReason && <p className="adm-bad small">Reason: {d.rejectionReason}</p>}
      {d.reviewedBy && <p className="adm-muted small">{DOC_LABEL[d.status]} by {d.reviewedBy.name}, {fmtWhen(d.reviewedAt)}</p>}

      <div className="adm-actions">
        {canOpen && <button className="btn btn-ghost btn-sm" onClick={toggleView}>{url ? 'Hide' : 'View'}</button>}
        {canDecide && d.status !== 'approved' && (
          <button className="btn btn-ok btn-sm" disabled={!!busy} onClick={() => act('doc-ok-' + d.id, () => approveDocument(userId, d.id))}>Approve</button>
        )}
        {canDecide && d.status !== 'rejected' && !rejecting && (
          <button className="btn btn-ghost btn-sm adm-danger-text" onClick={() => setRejecting(true)}>Reject…</button>
        )}
      </div>
      {canOpen && <p className="adm-muted tiny">Each opening is logged with your name and IP address.</p>}
      {viewError && <p className="form-error">{viewError}</p>}
      {url && (
        d.contentType === 'application/pdf'
          ? <iframe className="adm-viewer" src={url} title={d.label} />
          : <img className="adm-viewer" src={url} alt={d.label} />
      )}

      {rejecting && (
        <form className="adm-reason" onSubmit={reject} noValidate>
          <label className="field"><span>Why is this document rejected? (sent to the driver)</span>
            <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. The photo is blurred; the licence number isn't readable." autoFocus />
            {reasonError && <small className="field-error" role="alert">{reasonError}</small>}
          </label>
          <div className="adm-actions">
            <button className="btn btn-danger btn-sm" type="submit" disabled={!!busy}>Reject document</button>
            <button className="btn btn-ghost btn-sm" type="button" onClick={() => { setRejecting(false); setReasonError(''); }}>Cancel</button>
          </div>
        </form>
      )}
    </div>
  );
}

function Decisions({ data, userId, busy, act }) {
  const v = data.verification;
  const [masked, setMasked] = useState(false);
  const [note, setNote] = useState('');
  const [mode, setMode] = useState(''); // '' | 'reject' | 'revoke'
  const [reason, setReason] = useState('');
  const [unmasked, setUnmasked] = useState(false);
  const [reasonError, setReasonError] = useState('');

  async function submitReason(e) {
    e.preventDefault();
    if (!reason.trim()) return setReasonError('Enter a reason. The driver sees it and it is emailed to them.');
    setReasonError('');
    const ok = await act(mode, () => (mode === 'reject' ? rejectProfile(userId, reason.trim(), unmasked) : revokeProfile(userId, reason.trim())));
    if (ok) { setMode(''); setReason(''); }
  }

  if (v.status === 'pending') {
    const anyRejected = data.canRequestResubmit;
    return (
      <div className="adm-card adm-decide">
        <h2>Decision</h2>
        <p className="small adm-muted">Approve every document first. Rejecting a document needs a reason, then ask the driver to re-upload.</p>

        {v.isAadhaar && (
          <label className="check"><input type="checkbox" checked={masked} onChange={(e) => setMasked(e.target.checked)} /> I checked that the Aadhaar copy is masked.</label>
        )}
        <button className="btn btn-primary" disabled={!data.canApprove || (v.isAadhaar && !masked) || !!busy}
          onClick={() => act('approve', () => approveProfile(userId, masked))}>
          {busy === 'approve' ? 'Approving…' : 'Approve profile'}
        </button>
        {!data.canApprove && <p className="tiny adm-muted">Enabled once every document is approved.</p>}

        <hr />
        <label className="field"><span>Note to the driver (optional; the rejected documents' reasons are included)</span>
          <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></label>
        <button className="btn btn-accent" disabled={!anyRejected || !!busy} onClick={() => act('resubmit', () => requestResubmit(userId, note.trim()))}>
          Ask driver to re-upload
        </button>
        {!anyRejected && <p className="tiny adm-muted">Reject at least one document first.</p>}

        <hr />
        {mode !== 'reject' ? (
          <button className="btn btn-ghost adm-danger-text" onClick={() => setMode('reject')}>Reject profile…</button>
        ) : (
          <ReasonForm title="Reject the whole profile (the driver must submit everything again)" reason={reason} setReason={setReason}
            error={reasonError} onSubmit={submitReason} onCancel={() => setMode('')} busy={busy} label="Reject profile">
            {v.isAadhaar && <label className="check"><input type="checkbox" checked={unmasked} onChange={(e) => setUnmasked(e.target.checked)} /> The Aadhaar copy is NOT masked (delete it now)</label>}
          </ReasonForm>
        )}
      </div>
    );
  }

  if (v.status === 'approved') {
    return (
      <div className="adm-card adm-decide">
        <h2>Decision</h2>
        <p className="small">Approved. The driver can post rides.</p>
        {mode !== 'revoke' ? (
          <button className="btn btn-ghost adm-danger-text" onClick={() => setMode('revoke')}>Revoke approval…</button>
        ) : (
          <ReasonForm title="Revoke approval (hides their rides from search)" reason={reason} setReason={setReason}
            error={reasonError} onSubmit={submitReason} onCancel={() => setMode('')} busy={busy} label="Revoke approval" />
        )}
      </div>
    );
  }

  return (
    <div className="adm-card adm-decide">
      <h2>Decision</h2>
      <p className="small adm-muted">
        {v.status === 'resubmit_requested'
          ? 'Waiting for the driver to re-upload the rejected documents. It comes back to the queue when they do.'
          : 'Nothing to decide until the driver submits again.'}
      </p>
    </div>
  );
}

function ReasonForm({ title, reason, setReason, error, onSubmit, onCancel, busy, label, children }) {
  return (
    <form className="adm-reason" onSubmit={onSubmit} noValidate>
      <label className="field"><span>{title}</span>
        <textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (sent to the driver)" autoFocus />
        {error && <small className="field-error" role="alert">{error}</small>}
      </label>
      {children}
      <div className="adm-actions">
        <button className="btn btn-danger btn-sm" type="submit" disabled={!!busy}>{label}</button>
        <button className="btn btn-ghost btn-sm" type="button" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

function Emails({ emails, canRetry, busy, act }) {
  return (
    <div className="adm-card">
      <h2>Emails</h2>
      {emails.length === 0 ? <p className="adm-muted small">No emails yet.</p> : (
        <ul className="adm-emails">
          {emails.map((e) => (
            <li key={e.id}>
              <div>
                <strong>{e.kindLabel}</strong> <span className={'adm-email es-' + e.status}>{EMAIL_LABEL[e.status]}</span>
                <div className="tiny adm-muted">{e.toEmail || 'no address'} · {fmtWhen(e.sentAt || e.createdAt)}{e.attempts > 1 && ` · ${e.attempts} attempts`}</div>
                {e.status === 'failed' && e.lastError && <div className="tiny adm-bad">{e.lastError}</div>}
              </div>
              {canRetry && e.status === 'failed' && (
                <button className="btn btn-ghost btn-sm" disabled={!!busy} onClick={() => act('email-' + e.id, () => retryEmail(e.id))}>
                  {busy === 'email-' + e.id ? 'Sending…' : 'Retry'}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
