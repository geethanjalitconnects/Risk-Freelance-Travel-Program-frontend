import { navigate } from '../../router.jsx';
import { useApi } from '../../lib/useApi.js';
import { fmtWhen, getAudit } from '../adminApi.js';

function describe(details) {
  const parts = [];
  if (details.document) parts.push(details.document.replace('_', ' '));
  if (details.status) parts.push(`→ ${details.status.replace('_', ' ')}`);
  if (details.email) parts.push(`${details.email.replace('_', ' ')} email${details.sent === false ? ' (failed again)' : ''}`);
  if (details.reason) parts.push(`“${details.reason}”`);
  return parts.join(' · ');
}

export default function Audit({ query }) {
  const page = Number(query.page || 1);
  const action = query.action || '';
  const { data, error, loading, reload } = useApi(() => getAudit({ page, action }), [page, action]);
  const go = (patch) => navigate('/admin/audit', { page: 1, action, ...patch });

  return (
    <section>
      <div className="adm-head">
        <h1>Audit log</h1>
        <label className="adm-filter">Action{' '}
          <select value={action} onChange={(e) => go({ action: e.target.value })}>
            <option value="">All actions</option>
            {data?.actions?.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
          </select>
        </label>
      </div>

      {error && <p className="callout warn">{error.message} <button className="btn btn-sm btn-ghost" onClick={reload}>Retry</button></p>}
      {loading && !data && <p className="adm-muted">Loading…</p>}

      {data && (
        <div className="adm-card adm-table-wrap">
          <table className="adm-table">
            <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Driver</th><th>Details</th><th>IP</th></tr></thead>
            <tbody>
              {data.results.length === 0 && <tr><td colSpan={6} className="adm-muted">No entries.</td></tr>}
              {data.results.map((e) => (
                <tr key={e.id}>
                  <td className="small nowrap">{fmtWhen(e.at)}</td>
                  <td>{e.actor || '—'}</td>
                  <td><span className={'adm-act a-' + e.action}>{e.actionLabel}</span></td>
                  <td>{e.targetUser ? <a href={`#/admin/review/${e.targetUser.id}`}>{e.targetUser.name}</a> : '—'}</td>
                  <td className="small">{describe(e.details)}</td>
                  <td className="small mono">{e.ipAddress || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && data.pages > 1 && (
        <div className="adm-pager">
          <button className="btn btn-ghost btn-sm" disabled={page <= 1} onClick={() => go({ page: page - 1 })}>Previous</button>
          <span>Page {data.page} of {data.pages} · {data.count} entries</span>
          <button className="btn btn-ghost btn-sm" disabled={page >= data.pages} onClick={() => go({ page: page + 1 })}>Next</button>
        </div>
      )}
    </section>
  );
}
