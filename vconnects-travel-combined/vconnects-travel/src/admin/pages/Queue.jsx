import { useState } from 'react';
import { navigate } from '../../router.jsx';
import { useApi } from '../../lib/useApi.js';
import { STATUS_LABEL, fmtWhen, getQueue } from '../adminApi.js';

const TABS = [
  ['pending', 'Pending'],
  ['resubmit_requested', 'Re-upload requested'],
  ['approved', 'Approved'],
  ['rejected', 'Rejected / revoked'],
  ['all', 'All'],
];

export default function Queue({ query }) {
  const status = query.status || 'pending';
  const page = Number(query.page || 1);
  const [q, setQ] = useState(query.q || '');
  const { data, error, loading, reload } = useApi(() => getQueue({ status, q: query.q || '', page }), [status, query.q, page]);
  const go = (patch) => navigate('/admin/queue', { status, q: query.q || '', page: 1, ...patch });

  return (
    <section>
      <div className="adm-head">
        <h1>Review queue</h1>
        <form className="adm-search" onSubmit={(e) => { e.preventDefault(); go({ q: q.trim() }); }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, phone, email or vehicle number" aria-label="Search" />
          <button className="btn btn-ghost btn-sm" type="submit">Search</button>
        </form>
      </div>

      <div className="adm-tabs" role="tablist">
        {TABS.map(([key, label]) => (
          <button key={key} role="tab" aria-selected={status === key} className={'adm-pill' + (status === key ? ' on' : '')} onClick={() => go({ status: key })}>
            {label}{data?.counts?.[key] !== undefined && <span className="adm-count">{data.counts[key]}</span>}
          </button>
        ))}
      </div>

      {error && <p className="callout warn">{error.message} <button className="btn btn-sm btn-ghost" onClick={reload}>Retry</button></p>}
      {loading && !data && <p className="adm-muted">Loading…</p>}

      {data && (
        data.results.length === 0 ? (
          <div className="adm-card adm-empty"><p>Nothing here{status === 'pending' ? ': the queue is clear.' : '.'}</p></div>
        ) : (
          <div className="adm-card adm-table-wrap">
            <table className="adm-table">
              <thead>
                <tr><th>Driver</th><th>Vehicle</th><th>Status</th><th>Documents</th><th>Submitted</th><th /></tr>
              </thead>
              <tbody>
                {data.results.map((r) => (
                  <tr key={r.userId} onClick={() => navigate(`/admin/review/${r.userId}`)} className="adm-row">
                    <td>
                      <strong>{r.name || '(no name)'}</strong>
                      <div className="adm-muted small">{r.phone}{r.email && ` · ${r.email}`}</div>
                    </td>
                    <td className="mono">{r.vehicleNumber}<div className="adm-muted small">{r.idType}</div></td>
                    <td>
                      <span className={'adm-status s-' + r.status}>{STATUS_LABEL[r.status]}</span>
                      {r.emailFailed && <span className="adm-flag">Email failed</span>}
                    </td>
                    <td className="small">
                      {r.documents.approved}/{r.documents.total} approved
                      {r.documents.rejected > 0 && <div className="adm-bad">{r.documents.rejected} rejected</div>}
                    </td>
                    <td className="small">{fmtWhen(r.submittedAt)}</td>
                    <td><a className="btn btn-sm btn-primary" href={`#/admin/review/${r.userId}`} onClick={(e) => e.stopPropagation()}>Review</a></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      {data && data.pages > 1 && (
        <div className="adm-pager">
          <button className="btn btn-ghost btn-sm" disabled={page <= 1} onClick={() => go({ page: page - 1 })}>Previous</button>
          <span>Page {data.page} of {data.pages}</span>
          <button className="btn btn-ghost btn-sm" disabled={page >= data.pages} onClick={() => go({ page: page + 1 })}>Next</button>
        </div>
      )}
    </section>
  );
}
