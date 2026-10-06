import { request } from './client';
import type { CollectionPage, ProjectView, TaskSummary } from './types';
export const listProjects = () => request<CollectionPage<ProjectView>>('/projects?limit=50');
export const getProject = (id: string) => request<ProjectView>(`/projects/${encodeURIComponent(id)}`);
export const createProject = (body: { key: string; name: string; description: string }) => request<ProjectView>('/projects', { method: 'POST', body: JSON.stringify(body) });
export const listProjectTasks = (id: string) => request<CollectionPage<TaskSummary>>(`/projects/${encodeURIComponent(id)}/tasks?limit=50`);
export const createTask = (id: string, body: { title: string; requirement: string }) => request<TaskSummary>(`/projects/${encodeURIComponent(id)}/tasks`, { method: 'POST', body: JSON.stringify(body) });
