import { useCallback } from 'react';
import { Link } from 'react-router-dom';
import { getProject, listProjectTasks } from '../api/projects';
import { useResource } from '../app/useResource';
import { LoadingState, EmptyState, ErrorState, TruncationNotice } from '../components/Feedback';
import { DateTime } from '../components/DateTime';
import { TaskForm } from '../components/Forms';
import { StatusBadge } from '../components/StatusBadge';
export function ProjectDetailPage({ projectId }: { projectId: string }) {
  const project = useResource(useCallback(() => getProject(projectId), [projectId]));
  const tasks = useResource(useCallback(() => listProjectTasks(projectId), [projectId]));
  return <><header className="page-header"><Link to="/projects" className="muted">← Projects</Link><h1>{project.data?.name || 'Project Detail'}</h1></header>
    {project.loading && <LoadingState>Loading Project…</LoadingState>}{project.error && <ErrorState error={project.error} retry={() => void project.reload()} />}
    {project.data && <><section className="panel project-summary"><p className="mono">{project.data.key}</p><p className="prose">{project.data.description || 'No description provided.'}</p><dl className="metadata"><div><dt>Created</dt><dd><DateTime value={project.data.created_at} /></dd></div><div><dt>Updated</dt><dd><DateTime value={project.data.updated_at} /></dd></div><div><dt>Project ID</dt><dd className="mono">{project.data.id}</dd></div></dl></section>
      <div className="content-grid"><section className="panel"><div className="panel-heading"><h2>Tasks</h2><button type="button" disabled={tasks.loading} onClick={() => void tasks.reload()}>Refresh</button></div>
        {tasks.loading && <LoadingState>Loading Tasks…</LoadingState>}{tasks.error && <ErrorState error={tasks.error} retry={() => void tasks.reload()} />}
        {tasks.data && <>{!tasks.data.items.length ? <EmptyState>No Tasks in this Project yet.</EmptyState> : <ul className="record-list">{tasks.data.items.map(task => <li key={task.id}><div><Link to={`/tasks/${task.id}`} className="record-title">{task.title}</Link><p className="muted"><DateTime value={task.updated_at} /></p></div><StatusBadge state={task.state} /></li>)}</ul>}<TruncationNotice truncated={tasks.data.truncated} /></>}
      </section><TaskForm projectId={projectId} onCreated={async () => { await tasks.reload(); }} /></div>
    </>}
  </>;
}
