import { Link } from '../router.jsx';
import Icon from './Icon.jsx';

// Driver verification status at a glance. `v` is GET /me/driver-verification.
// The server enforces the same rule: only approved drivers can post or edit rides.
export default function VerificationBanner({ v, onReupload }) {
  if (!v) return null;
  const s = v.status;

  if (s === 'approved') {
    return (
      <div className="vbanner vb-ok" role="status">
        <Icon name="check" size={18} />
        <div className="vb-text"><strong>You are a verified driver.</strong> You can post rides.</div>
        <Link to="/publish" className="btn btn-accent btn-sm">Post a ride</Link>
      </div>
    );
  }

  if (s === 'pending') {
    return (
      <div className="vbanner vb-info" role="status">
        <Icon name="clock" size={18} />
        <div className="vb-text"><strong>Your documents are under review.</strong> You can post rides once they are approved.</div>
        <button className="btn btn-sm btn-ghost" disabled title="Available once your documents are approved">Post a ride</button>
      </div>
    );
  }

  if (s === 'rejected' || s === 'resubmit_requested' || s === 'revoked') {
    const title = {
      rejected: 'Your verification was rejected.',
      resubmit_requested: 'Please re-upload some of your documents.',
      revoked: 'Your verification was revoked.',
    }[s];
    const reupload = onReupload
      ? <button className="btn btn-accent btn-sm" onClick={onReupload}>Re-upload documents</button>
      : <Link to="/verification" className="btn btn-accent btn-sm">Re-upload documents</Link>;
    return (
      <div className="vbanner vb-warn" role="alert">
        <Icon name="alert" size={18} />
        <div className="vb-text">
          <strong>{title}</strong>
          {v.reason && <span className="vb-reason">Reason: {v.reason}</span>}
        </div>
        {reupload}
      </div>
    );
  }

  return (
    <div className="vbanner vb-info" role="status">
      <Icon name="shield" size={18} />
      <div className="vb-text"><strong>Want to offer rides?</strong> Verify your licence, ID and vehicle first.</div>
      <Link to="/verification" className="btn btn-primary btn-sm">Submit documents</Link>
    </div>
  );
}
