import { useState } from 'react';

// There is no contact endpoint on the API yet, so the form opens the visitor's mail app.
// Set VITE_SUPPORT_EMAIL in .env to your real support address.
const SUPPORT = import.meta.env.VITE_SUPPORT_EMAIL || 'support@vconnects.example';
const TOPICS = ['General question', 'Report a safety issue', 'Problem with a booking', 'Driver verification', 'Feedback'];

export default function Contact() {
  const [form, setForm] = useState({ name: '', email: '', topic: TOPICS[0], message: '' });
  const [errors, setErrors] = useState({});
  const [sent, setSent] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = (e) => {
    e.preventDefault();
    const err = {};
    if (!form.name.trim()) err.name = 'Enter your name.';
    if (!/^\S+@\S+\.\S+$/.test(form.email)) err.email = 'Enter a valid email address.';
    if (form.message.trim().length < 10) err.message = 'Tell us a little more (at least 10 characters).';
    setErrors(err);
    if (Object.keys(err).length) return;
    const body = `${form.message}\n\n— ${form.name} (${form.email})`;
    window.location.href = `mailto:${SUPPORT}?subject=${encodeURIComponent('[VConnects] ' + form.topic)}&body=${encodeURIComponent(body)}`;
    setSent(true);
  };

  return (
    <div className="container page info-page narrow">
      <span className="tag">Contact</span>
      <h1 className="page-title">Get in touch</h1>
      <p className="muted lead">For an emergency on a trip, call <a href="tel:112">112</a> first.</p>
      <form className="panel form-stack" onSubmit={submit} noValidate>
        <div className="row2">
          <label className="field"><span>Name</span><input value={form.name} onChange={set('name')} autoComplete="name" />{errors.name && <span className="field-error">{errors.name}</span>}</label>
          <label className="field"><span>Email</span><input type="email" value={form.email} onChange={set('email')} autoComplete="email" />{errors.email && <span className="field-error">{errors.email}</span>}</label>
        </div>
        <label className="field"><span>Topic</span><select value={form.topic} onChange={set('topic')}>{TOPICS.map((t) => <option key={t}>{t}</option>)}</select></label>
        <label className="field"><span>Message</span><textarea rows={5} value={form.message} onChange={set('message')} />{errors.message && <span className="field-error">{errors.message}</span>}</label>
        <button className="btn btn-accent" type="submit">Send message</button>
        {sent && <p className="callout">Your mail app should have opened with the message ready to send to {SUPPORT}.</p>}
      </form>
    </div>
  );
}
