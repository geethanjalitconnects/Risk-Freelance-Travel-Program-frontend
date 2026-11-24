import { useState } from 'react';
import { navigate } from '../../router.jsx';
import { changePassword, logout } from '../adminApi.js';

export default function ChangePassword({ forced }) {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    const err = {};
    if (!current) err.currentPassword = 'Enter your current password.';
    if (next.length < 12) err.newPassword = 'Use at least 12 characters.';
    else if (next !== confirm) err.confirm = 'The passwords don’t match.';
    setErrors(err);
    if (Object.keys(err).length) return;
    setBusy(true);
    try {
      await changePassword(current, next);
      navigate('/admin/queue');
    } catch (ex) {
      setErrors({
        currentPassword: ex.field?.('current_password') || ex.field?.('currentPassword'),
        newPassword: ex.field?.('new_password') || ex.field?.('newPassword'),
        form: ex.field?.('current_password') || ex.field?.('new_password') || ex.field?.('currentPassword') || ex.field?.('newPassword') ? '' : ex.message,
      });
    } finally {
      setBusy(false);
    }
  }

  const Err = ({ k }) => (errors[k] ? <small className="field-error" role="alert">{errors[k]}</small> : null);

  return (
    <div className="adm adm-center">
      <form className="adm-card adm-login" onSubmit={submit} noValidate>
        <div className="adm-brand big">VConnects <span>Admin</span></div>
        <h1>{forced ? 'Choose a new password' : 'Change password'}</h1>
        {forced && <p className="adm-muted">This is your first sign-in. Choose your own password before continuing.</p>}
        <label className="field"><span>Current password</span>
          <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" />
          <Err k="currentPassword" /></label>
        <label className="field"><span>New password (12+ characters, not a common password)</span>
          <input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" />
          <Err k="newPassword" /></label>
        <label className="field"><span>Repeat new password</span>
          <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
          <Err k="confirm" /></label>
        {errors.form && <p className="form-error" role="alert">{errors.form}</p>}
        <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save password'}</button>
        <button className="btn btn-ghost" type="button" onClick={logout}>Sign out</button>
      </form>
    </div>
  );
}
