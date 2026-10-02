import { request } from './client';
import type { CollectionPage, TaskDetail, TimelineEntry } from './types';
export const getTask = (id: string) => request<TaskDetail>(`/tasks/${encodeURIComponent(id)}`);
export const getTimeline = (id: string) => request<CollectionPage<TimelineEntry>>(`/tasks/${encodeURIComponent(id)}/timeline?limit=100`);
export const runTask = (id: string) => request<TaskDetail>(`/tasks/${encodeURIComponent(id)}/run`, { method: 'POST' });
export const resumeTask = (id: string) => request<TaskDetail>(`/tasks/${encodeURIComponent(id)}/resume`, { method: 'POST' });
