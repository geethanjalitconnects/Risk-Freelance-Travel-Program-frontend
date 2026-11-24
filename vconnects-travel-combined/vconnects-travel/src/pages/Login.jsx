import { useEffect, useRef, useState } from 'react';
import { navigate } from '../router.jsx';
import { GENDER_OPTIONS, sendOtp, updateMe, useAuth, verifyOtp } from '../lib/auth.js';

// Only follow in-app paths after sign-in (never another site).
const safeNext = (next) => (next && next.startsWith('/') && !next.startsWith('//') ? next : '/');

function useCountdown() {
  const [left, setLeft] = useState(0);
  useEffect(() => {
    if (left <= 0) return undefined;
    const t = setTimeout(() => setLeft((n) => n - 1), 1000);
    return () => clearTimeout(t);
  }, [left]);
  return [left, setLeft];
}

export default function Login({ query = {} }) {
  const auth = useAuth();
  const next = safeNext(query.next);
  const [step, setStep] = useState('email'); // email | code | details
  const [email, setEmail] = useState('');
  const [sentTo, setSentTo] = useState('');
  const [code, setCode] = useState('');
  const [details, setDetails] = useState({ name: '', gender: '', phone: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [resendIn, setResendIn] = useCountdown();
  const codeRef = useRef(null);

  // Already signed in: finish the sign-up details if they were skipped, otherwise move on.
  useEffect(() => {
    if (step !== 'email' || auth.status !== 'signed-in') return;
    if (auth.user?.profileComplete) navigate(next);
    else {
      setDetails({ name: auth.user?.name || '', gender: auth.user?.gender || '', phone: auth.user?.phone || '' });
      setStep('details');
    }
  }, [auth.status, auth.user, step, next]);

  useEffect(() => {
    if (step === 'code') codeRef.current?.focus();
  }, [step]);

  async function run(fn) {
    setBusy(true);
    setError('');
    try {
      await fn();
    } catch (e) {
      setError(e.message);
      if (e.data?.retryAfter) setResendIn(e.data.retryAfter);
    } finally {
      setBusy(false);
    }
  }

  const send = (e) => {
    e?.preventDefault();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) return setError('Enter a valid email address, e.g. you@example.com.');
    return run(async () => {
      const res = await sendOtp(email.trim());
      setSentTo(res.email);
      setResendIn(res.resendIn);
      setCode('');
      setStep('code');
    });
  };

  const verify = (e) => {
    e.preventDefault();
    if (!/^\d{6}$/.test(code)) return setError('Enter the 6-digit code.');
    return run(async () => {
      try {
        const res = await verifyOtp(sentTo, code);
        if (res.user.profileComplete) return navigate(next);
        setDetails({ name: res.user.name || '', gender: res.user.gender || '', phone: res.user.phone || '' });
        setStep('details');
      } catch (err) {
        if (err.data?.attemptsLeft) err.message = `${err.message} ${err.data.attemptsLeft} attempt${err.data.attemptsLeft > 1 ? 's' : ''} left.`;
        throw err;
      }
    });
  };

  const resend = () =>
    run(async () => {
      const res = await sendOtp(sentTo);
      setResendIn(res.resendIn);
      setCode('');
    });

  const saveDetails = (e) => {
    e.preventDefault();
    if (!details.name.trim()) return setError('Enter your name.');
    if (!/^\+?[0-9 -]{10,17}$/.test(details.phone.trim())) return setError('Enter a valid mobile number, e.g. +91 98765 43210.');
    return run(async () => {
      await updateMe({ name: details.name.trim(), gender: details.gender, phone: details.phone.trim() });
      navigate(next);
    });
  };

  return (
    <div className="container page narrow">
      {step === 'email' && (
        <form className="panel form-stack" onSubmit={send} noValidate>
          <h1 className="page-title">Sign in or sign up</h1>
          <p className="muted">Enter your email address. We’ll email you a 6-digit code. New here? The same step creates your account.</p>
          <label className="field">
            <span>Email address</span>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} inputMode="email" autoComplete="email"
              autoCapitalize="none" spellCheck={false} placeholder="you@example.com" autoFocus />
          </label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="btn btn-accent" type="submit" disabled={busy || resendIn > 0}>
            {busy ? 'Sending…' : resendIn > 0 ? `Try again in ${resendIn}s` : 'Send code'}
          </button>
        </form>
      )}

      {step === 'code' && (
        <form className="panel form-stack" onSubmit={verify} noValidate>
          <h1 className="page-title">Enter your code</h1>
          <p className="muted">We emailed a 6-digit code to <b>{sentTo}</b>. It expires in 5 minutes. Check your spam folder if you don’t see it.</p>
          <label className="field">
            <span>Verification code</span>
            <input
              ref={codeRef}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="••••••"
              maxLength={6}
            />
          </label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="btn btn-accent" type="submit" disabled={busy}>{busy ? 'Checking…' : 'Verify and continue'}</button>
          <div className="row2">
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setStep('email'); setError(''); setResendIn(0); }}>Change email</button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={resend} disabled={busy || resendIn > 0}>
              {resendIn > 0 ? `Resend code in ${resendIn}s` : 'Resend code'}
            </button>
          </div>
          {import.meta.env.DEV && <p className="fine">Development: unless email sending is set up, the email with the code is printed in the backend server console.</p>}
        </form>
      )}

      {step === 'details' && (
        <form className="panel form-stack" onSubmit={saveDetails} noValidate>
          <h1 className="page-title">Welcome to VConnects</h1>
          <p className="muted">Tell us a little about you. Drivers and passengers see your name on rides; your mobile number is shared only with the other side of a confirmed booking and used for SOS.</p>
          <label className="field">
            <span>Full name</span>
            <input value={details.name} onChange={(e) => setDetails({ ...details, name: e.target.value })} autoComplete="name" autoFocus />
          </label>
          <label className="field">
            <span>Mobile number</span>
            <input value={details.phone} onChange={(e) => setDetails({ ...details, phone: e.target.value })} inputMode="tel" autoComplete="tel" placeholder="+91 98765 43210" />
          </label>
          <label className="field">
            <span>Gender (enables women-only and men-only rides)</span>
            <select value={details.gender} onChange={(e) => setDetails({ ...details, gender: e.target.value })}>
              {GENDER_OPTIONS.map((g) => <option key={g.value} value={g.value}>{g.label}</option>)}
            </select>
          </label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="btn btn-accent" type="submit" disabled={busy}>{busy ? 'Saving…' : 'Continue'}</button>
        </form>
      )}
    </div>
  );
}
