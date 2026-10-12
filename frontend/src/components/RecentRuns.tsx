import { Link } from 'react-router-dom';
import { DateTime } from './DateTime';
import { StateBadge } from './StatusBadge';
import { TruncationNotice } from './Feedback';
import { runsPath } from '../api/runs';
import type { QARun } from '../api/runTypes';
import type { CollectionPage } from '../api/types';

// No detail fan-out: this component uses only the bounded Run metadata response.
export function RecentRuns({page, projectId, campaignId, maximum=50}: {page:CollectionPage<QARun>;projectId:string;campaignId:string;maximum?:number}) {
  const visible = page.items.slice(0,maximum);
  return <section className="panel recent-runs"><div className="panel-heading"><h3>Recent Runs</h3><span className="recent-runs-mode">SYNTHETIC · saved history</span></div>
    {!visible.length ? <p>No Runs yet. Nothing has been evaluated.</p> : <div className="campaign-table-scroll" role="region" aria-label="Recent Runs" tabIndex={0}><table className="campaign-table"><caption>Saved Run snapshots — no external Target was tested</caption><thead><tr><th>Run</th><th>Target / environment</th><th>Tests</th><th>Execution status</th><th>QA outcome</th><th>Created</th></tr></thead><tbody>{visible.map(run=><tr key={run.id}><th className="recent-run-identity" scope="row"><Link to={runsPath(projectId,campaignId,run.id)}>RUN-{String(run.run_number).padStart(3,'0')}</Link></th><td>{run.target_snapshot?<>{run.target_snapshot.name}<br/><span className="hint">{run.target_snapshot.type} · {run.target_snapshot.environment}</span></>:<span className="muted">Target not captured</span>}</td><td className="recent-run-count">{run.test_count}</td><td><StateBadge status={run.execution_status}/></td><td><StateBadge status={run.qa_outcome}/></td><td className="recent-run-date"><DateTime value={run.created_at}/></td></tr>)}</tbody></table></div>}
    {page.items.length>maximum && <p className="hint">Showing {visible.length} of {page.items.length} returned Runs. Open Results for the bounded list.</p>}
    <TruncationNotice truncated={page.truncated}/>
  </section>;
}
