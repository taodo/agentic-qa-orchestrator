import { useCallback, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getProject, listProjectTasks } from '../api/projects';
import { listCampaigns, campaignPath } from '../api/campaigns';
import { useResource } from '../app/useResource';
import { LoadingState, EmptyState, ErrorState, TruncationNotice } from '../components/Feedback';
import { DateTime } from '../components/DateTime';
import { TaskForm } from '../components/Forms';
import { CampaignForm } from '../components/CampaignForm';
import { CampaignStatusBadge } from '../components/CampaignStatusBadge';
import { StatusBadge } from '../components/StatusBadge';
import { RuntimeReadiness } from '../components/RuntimeReadiness';

function ProjectCampaigns({ projectId }: { projectId: string }) {
  const campaigns = useResource(useCallback(() => listCampaigns(projectId), [projectId]));
  const navigate = useNavigate();
  return <div className="content-grid"><section className="panel" aria-labelledby="campaign-list-heading">
    <div className="panel-heading"><h2 id="campaign-list-heading">QA Campaigns</h2><button disabled={campaigns.loading} onClick={() => void campaigns.reload()}>Refresh Campaigns</button></div>
    {campaigns.loading ? <LoadingState>Loading Campaigns…</LoadingState> : campaigns.error ? <ErrorState error={campaigns.error} retry={() => void campaigns.reload()} /> : campaigns.data && <>
      {!campaigns.data.items.length ? <EmptyState>No Campaigns yet. Create a Campaign to prepare requirements, test specifications, review and coverage for a QA initiative.</EmptyState>
        : <ul className="record-list">{campaigns.data.items.map(campaign => <li key={campaign.id}><div>
          <Link className="record-title" to={campaignPath(projectId, campaign.id)}>{campaign.name}</Link>
          <p className="prose muted">{campaign.objective || 'No objective provided.'}</p><p className="muted">Updated <DateTime value={campaign.updated_at} /></p>
        </div><div className="record-meta"><span className="muted">Preparation</span><CampaignStatusBadge status={campaign.status} /></div></li>)}</ul>}
      <TruncationNotice truncated={campaigns.data.truncated} /></>}
  </section><CampaignForm projectId={projectId} onCreated={campaign => navigate(campaignPath(projectId, campaign.id))} /></div>;
}

function LegacyTasks({ projectId }: { projectId: string }) {
  const tasks = useResource(useCallback(() => listProjectTasks(projectId), [projectId]));
  return <><RuntimeReadiness projectId={projectId} /><div className="content-grid"><section className="panel"><div className="panel-heading"><h2>Tasks</h2>
    <button disabled={tasks.loading} onClick={() => void tasks.reload()}>Refresh Tasks</button></div>
    {tasks.loading && <LoadingState>Loading Tasks…</LoadingState>}{tasks.error && <ErrorState error={tasks.error} retry={() => void tasks.reload()} />}
    {tasks.data && <>{!tasks.data.items.length ? <EmptyState>No Tasks in this Project yet.</EmptyState> : <ul className="record-list">{tasks.data.items.map(task => <li key={task.id}><div>
      <Link to={`/tasks/${task.id}`} className="record-title">{task.title}</Link><p className="muted"><DateTime value={task.updated_at} /></p>
    </div><StatusBadge state={task.state} /></li>)}</ul>}<TruncationNotice truncated={tasks.data.truncated} /></>}
  </section><TaskForm projectId={projectId} onCreated={async () => { await tasks.reload(); }} /></div></>;
}

export function ProjectDetailPage({ projectId }: { projectId: string }) {
  const project = useResource(useCallback(() => getProject(projectId), [projectId]));
  const [legacyOpen, setLegacyOpen] = useState(false);
  return <><header className="page-header"><Link to="/projects" className="muted">← Projects</Link><h1>{project.data?.name || 'Project'}</h1></header>
    {project.loading ? <LoadingState>Loading Project…</LoadingState> : project.error ? <ErrorState error={project.error} retry={() => void project.reload()} /> : project.data && <>
      <section className="panel project-summary"><p className="mono">{project.data.key}</p><p className="prose">{project.data.description || 'No description provided.'}</p>
        <dl className="metadata"><div><dt>Created</dt><dd><DateTime value={project.data.created_at} /></dd></div><div><dt>Updated</dt><dd><DateTime value={project.data.updated_at} /></dd></div></dl></section>
      <ProjectCampaigns projectId={projectId} />
      <section className="legacy-section"><button className="legacy-toggle" aria-expanded={legacyOpen} aria-controls="legacy-project-workflows" onClick={() => setLegacyOpen(value => !value)}>Legacy workflows</button>
        <p className="hint">Historical Task execution and runtime configuration. Campaign preparation stays separate.</p>
        <div id="legacy-project-workflows" hidden={!legacyOpen}>{legacyOpen && <LegacyTasks projectId={projectId} />}</div>
      </section>
    </>}
  </>;
}
