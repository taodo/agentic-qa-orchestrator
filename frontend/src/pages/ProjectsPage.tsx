import { useCallback } from 'react';
import { Link } from 'react-router-dom';
import { listProjects } from '../api/projects';
import { useResource } from '../app/useResource';
import { LoadingState, EmptyState, ErrorState, TruncationNotice } from '../components/Feedback';
import { DateTime } from '../components/DateTime';
import { ProjectForm } from '../components/Forms';
import { PageHeader } from '../components/WorkspaceUI';
import { ProductHelp } from '../components/ProductHelp';
export function ProjectsPage() {
  const projects = useResource(useCallback(listProjects, []));
  return <><PageHeader title="Projects" eyebrow="Workspace / Projects" description="Prepare QA campaigns from requirements and test specifications. Open a Project to create a Campaign and inspect review, traceability and readiness." />
    <ProductHelp />
    <div className="content-grid"><section className="panel"><div className="panel-heading"><h2>Project registry</h2><button type="button" disabled={projects.loading} onClick={() => void projects.reload()}>Refresh</button></div>
      {projects.loading && <LoadingState>Loading Projects…</LoadingState>}
      {projects.error && <ErrorState error={projects.error} retry={() => void projects.reload()} />}
      {projects.data && <>{!projects.data.items.length ? <EmptyState>No Projects yet. Create a Project to organize QA Campaigns. Campaign preparation does not require a source repository or execution runtime.</EmptyState> : <ul className="record-list">{projects.data.items.map(project => <li key={project.id}><div><Link to={`/projects/${project.id}`} className="record-title">{project.name}</Link><p className="mono muted">{project.key}</p></div><div className="record-meta"><span className="muted">Updated</span><DateTime value={project.updated_at} /></div></li>)}</ul>}<TruncationNotice truncated={projects.data.truncated} /></>}
    </section><ProjectForm onCreated={async () => { await projects.reload(); }} /></div>
  </>;
}
