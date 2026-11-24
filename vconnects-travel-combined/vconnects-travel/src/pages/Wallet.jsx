import { useRef, useState } from 'react';
import { Link } from '../router.jsx';
import { useAuth } from '../lib/auth.js';
import { useApi } from '../lib/useApi.js';
import { fmtDateTime, toIsoLocal } from '../lib/format.js';
import {
  REFUND_STATUS, WITHDRAWAL_STATUS, fmtPaise, getEarnings, getEarningsHistory, getMyPayments, newKey, requestWithdrawal,
} from '../lib/walletApi.js';
import Icon from '../components/Icon.jsx';
import SwipeButton from '../components/SwipeButton.jsx';

const fmtMs = (ms) => fmtDateTime(toIsoLocal(new Date(ms)));

// Earnings (drivers) and payments + refunds (passengers). Balances are read-only here: they change
// only through the server's ledger.
export default function Wallet({ query }) {
  const auth = useAuth();
  if (auth.status === 'loading') return <div className="container page"><p className="muted">Loading…</p></div>;
  if (auth.status !== 'signed-in') {
    return (
      <div className="container page narrow">
        <h1 className="page-title">Wallet</h1>
        <div className="panel form-stack">
          <p>Sign in to see your earnings, payments and refunds.</p>
          <Link to="/login?next=/wallet" className="btn btn-accent">Sign in or sign up</Link>
        </div>
      </div>
    );
  }
  return <WalletScreen userId={auth.user.id} tab={query?.tab} />;
}

function WalletScreen({ userId, tab: initialTab }) {
  const earnings = useApi(getEarnings, [userId]);
  const isDriver = earnings.data?.isDriver;
  const [tab, setTab] = useState(initialTab === 'payments' ? 'payments' : null);
  const current = tab || (isDriver ? 'earnings' : 'payments');

  return (
    <div className="container page narrow">
      <h1 className="page-title">Wallet</h1>
      {isDriver && (
        <div className="seg wallet-tabs" role="tablist">
          <button role="tab" aria-selected={current === 'earnings'} className={current === 'earnings' ? 'on' : ''} onClick={() => setTab('earnings')}>Earnings</button>
          <button role="tab" aria-selected={current === 'payments'} className={current === 'payments' ? 'on' : ''} onClick={() => setTab('payments')}>Payments and refunds</button>
        </div>
      )}
      {current === 'earnings' ? <Earnings e={earnings} userId={userId} /> : <Payments userId={userId} />}
    </div>
  );
}

// ---------------------------------------------------------------- driver earnings

function Earnings({ e, userId }) {
  const [page, setPage] = useState(1);
  const history = useApi(() => getEarningsHistory(page), [userId, page]);

  if (e.error) return <p className="callout warn">{e.error.message} <button className="btn btn-ghost btn-sm" onClick={e.reload}>Try again</button></p>;
  if (!e.data) return <p className="muted">Loading your earnings…</p>;
  const d = e.data;
  const refresh = () => { e.reload(); setPage(1); history.reload(); };

  return (
    <>
      <div className="wallet-stats">
        <div className="stat stat-main"><span>Available to withdraw</span><strong>{fmtPaise(d.available)}</strong></div>
        <div className="stat"><span>On hold</span><strong>{fmtPaise(d.held)}</strong><small className="muted">Released when each ride is verified complete</small></div>
        {d.owed > 0 && <div className="stat stat-owed"><span>Penalties owed</span><strong>{fmtPaise(d.owed)}</strong><small className="muted">Recovered from your next earnings</small></div>}
      </div>

      <Withdraw d={d} onDone={refresh} />

      <h2 className="sub">History</h2>
      {history.error ? (
        <p className="callout warn">{history.error.message} <button className="btn btn-ghost btn-sm" onClick={history.reload}>Try again</button></p>
      ) : !history.data ? (
        <p className="muted">Loading…</p>
      ) : history.data.count === 0 ? (
        <p className="muted">No earnings yet. Your earnings appear here when passengers pay for your rides.</p>
      ) : (
        <>
          <ul className="ledger">
            {history.data.results.map((x) => (
              <li key={x.id} className={'lg-' + x.type}>
                <div>
                  <b>{x.label}</b>
                  <span className="muted">{x.route ? `${x.route} · ` : ''}{fmtMs(x.at)}</span>
                  {x.type === 'adjustment' && <span className="muted">{x.description}</span>}
                </div>
                <div className="lg-right">
                  <strong className="lg-amount">{SIGN[x.type] ?? ''}{fmtPaise(x.amount)}</strong>
                  <span className={'chip ' + (STATUS_CHIP[x.status] || '')}>{STATUS_TEXT[x.status] || x.status}</span>
                </div>
              </li>
            ))}
          </ul>
          {history.data.pages > 1 && (
            <div className="live-actions pager">
              <button className="btn btn-ghost btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Newer</button>
              <span className="muted">Page {history.data.page} of {history.data.pages}</span>
              <button className="btn btn-ghost btn-sm" disabled={page >= history.data.pages} onClick={() => setPage(page + 1)}>Older</button>
            </div>
          )}
        </>
      )}
    </>
  );
}

const SIGN = { credit: '+', debit: '−', withdrawal: '−', reversal: '−', hold: '' };
const STATUS_TEXT = { held: 'On hold', completed: 'Done', ...WITHDRAWAL_STATUS };
const STATUS_CHIP = { completed: 'chip-ok', paid: 'chip-ok', failed: 'chip-warn', rejected: 'chip-warn' };

function Withdraw({ d, onDone }) {
  // One key per swipe: a network retry of the same swipe can never create a second withdrawal.
  const key = useRef(newKey());
  const [done, setDone] = useState(null);

  if (!d.payoutAccount) {
    return (
      <div className="vbanner vb-info" role="status">
        <Icon name="bell" size={18} />
        <div className="vb-text"><strong>Add your payout details first.</strong> Tell us the bank account or UPI id to pay your earnings to.</div>
        <Link to="/payout-details" className="btn btn-primary btn-sm">Add payout details</Link>
      </div>
    );
  }

  async function withdraw() {
    const w = await requestWithdrawal(key.current);
    key.current = newKey();
    setDone(w);
    onDone();
  }

  return (
    <div className="panel form-stack withdraw">
      <div className="payout-line">
        <span>Withdraw to <b>{d.payoutAccount.display}</b></span>
        <Link to="/payout-details" className="btn btn-ghost btn-sm">Change</Link>
      </div>
      {done ? (
        <p className="callout" role="status"><Icon name="check" size={16} /> {fmtPaise(done.amount)} withdrawal requested to {done.destination}.</p>
      ) : (
        <>
          <SwipeButton
            label={d.canWithdraw ? `Swipe to withdraw ${fmtPaise(d.available)}` : 'Withdraw'}
            busyLabel="Requesting…"
            doneLabel="Requested"
            disabled={!d.canWithdraw}
            onConfirm={withdraw}
          />
          {d.block && <p className="fine">{d.block.message}</p>}
          <p className="fine">Minimum {fmtPaise(d.minWithdrawal)} · up to {d.maxPerDay} withdrawals a day · your whole available balance is withdrawn.</p>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- passenger payments

function Payments({ userId }) {
  const { data, error, reload } = useApi(getMyPayments, [userId]);
  if (error) return <p className="callout warn">{error.message} <button className="btn btn-ghost btn-sm" onClick={reload}>Try again</button></p>;
  if (!data) return <p className="muted">Loading your payments…</p>;
  if (data.length === 0) {
    return (
      <div className="empty">
        <h3>No payments yet</h3>
        <p>Payments for your bookings and any refunds appear here. Refunds always go back to the card, UPI or bank account you paid with.</p>
        <Link to="/" className="btn btn-primary">Find a ride</Link>
      </div>
    );
  }
  return (
    <>
      <p className="muted">Refunds always go back to the card, UPI or bank account you paid with. They usually reach you in 5 to 7 working days.</p>
      <ul className="ledger">
        {data.map((p) => (
          <li key={p.id} className="lg-payment">
            <div>
              <b>{p.route || 'Booking'}</b>
              <span className="muted">Paid {fmtMs(p.at)}{p.method ? ` · ${p.method.toUpperCase()}` : ''}</span>
              {p.refunds.map((r) => (
                <span key={r.id} className="lg-refund">
                  {fmtPaise(r.amount)} refund · {r.reason} · <b>{REFUND_STATUS[r.status] || r.status}</b>
                </span>
              ))}
            </div>
            <div className="lg-right">
              <strong className="lg-amount">{fmtPaise(p.amount)}</strong>
              <span className={'chip ' + (p.status === 'captured' ? 'chip-ok' : 'chip-warn')}>{p.status === 'captured' ? 'Paid' : 'Failed'}</span>
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
