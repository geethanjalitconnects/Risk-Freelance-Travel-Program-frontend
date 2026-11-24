import { useState } from 'react';
import { navigate } from '../../router.jsx';
import { login } from '../adminApi.js';

export default function AdminLogin({ next }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    if (!username.trim() || !password) return setError('Enter your username and password.');
    setBusy(true);
    setError('');
    try {
      const s = await login(username.trim(), password);
      navigate(s.admin.mustChangePassword ? '/admin/password' : next || '/admin/queue');
    } catch (ex) {
      setError(ex.status === 429 ? ex.message || 'Too many attempts. Try again later.' : ex.message);
      setPassword('');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="adm adm-center">
      <form className="adm-card adm-login" onSubmit={submit} noValidate>
        <div className="adm-brand big">VConnects <span>Admin</span></div>
        <h1>Sign in</h1>
        <p className="adm-muted">For VConnects staff only.</p>
        <label className="field"><span>Username</span>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus /></label>
        <label className="field"><span>Password</span>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
    </div>
  );
}
