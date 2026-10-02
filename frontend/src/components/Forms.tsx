import { useRef, useState, type FormEvent } from 'react';
import { createProject, createTask } from '../api/projects';
import { publicError, type ApiError } from '../api/client';
import type { ProjectView, TaskSummary } from '../api/types';
import { ErrorState } from './Feedback';

export function ProjectForm({ onCreated }: { onCreated: (project: ProjectView) => Promise<void> }) {
  const gate = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError>();
  const [feedback, setFeedback] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (gate.current) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const key = String(data.get('key') || ''), name = String(data.get('name') || ''), description = String(data.get('description') || '');
    if (!key.trim() || !name.trim()) { setFeedback('Key and name are required.'); return; }
    gate.current = true; setBusy(true); setError(undefined); setFeedback('');
    try { const project = await createProject({ key, name, description }); form.reset(); await onCreated(project); setFeedback('Project created.'); }
    catch (failure) { setError(publicError(failure)); }
    finally { gate.current = false; setBusy(false); }
  }
  return <section className="panel"><h2>Create Project</h2><form onSubmit={submit}><fieldset disabled={busy}>
    <label htmlFor="project-key">Key <span className="muted">required</span></label><input id="project-key" name="key" required maxLength={64} placeholder="payment-api" />
    <p className="hint">Lowercase letters and numbers, separated by single hyphens.</p>
    <label htmlFor="project-name">Name <span className="muted">required</span></label><input id="project-name" name="name" required />
    <label htmlFor="project-description">Description</label><textarea id="project-description" name="description" rows={3} />
    <button type="submit">{busy ? 'Creating…' : 'Create Project'}</button>
  </fieldset>{error && <ErrorState error={error} />}<p role="status">{feedback}</p></form></section>;
}

export function TaskForm({ projectId, onCreated }: { projectId: string; onCreated: (task: TaskSummary) => Promise<void> }) {
  const gate = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError>();
  const [feedback, setFeedback] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (gate.current) return;
    const form = event.currentTarget, data = new FormData(form);
    const title = String(data.get('title') || ''), requirement = String(data.get('requirement') || '');
    if (!title.trim() || !requirement.trim()) { setFeedback('Title and requirement are required.'); return; }
    gate.current = true; setBusy(true); setError(undefined); setFeedback('');
    try { const task = await createTask(projectId, { title, requirement }); form.reset(); await onCreated(task); setFeedback('Task created.'); }
    catch (failure) { setError(publicError(failure)); }
    finally { gate.current = false; setBusy(false); }
  }
  return <section className="panel"><h2>Create Task</h2><form onSubmit={submit}><fieldset disabled={busy}>
    <label htmlFor="task-title">Title <span className="muted">required</span></label><input id="task-title" name="title" required />
    <label htmlFor="task-requirement">Requirement <span className="muted">required</span></label><textarea id="task-requirement" name="requirement" rows={5} required />
    <button type="submit">{busy ? 'Creating…' : 'Create Task'}</button>
  </fieldset>{error && <ErrorState error={error} />}<p role="status">{feedback}</p></form></section>;
}
