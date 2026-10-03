import { Navigate, Routes, Route, useParams, Link } from 'react-router-dom';
import { AppShell } from './AppShell';
import { ProjectsPage } from '../pages/ProjectsPage';
import { ProjectDetailPage } from '../pages/ProjectDetailPage';
import { TaskDetailPage } from '../pages/TaskDetailPage';
import { OperationsPage } from '../pages/OperationsPage';
function ProjectRoute() { const { projectId = '' } = useParams(); return <ProjectDetailPage key={projectId} projectId={projectId} />; }
function TaskRoute() { const { taskId = '' } = useParams(); return <TaskDetailPage key={taskId} taskId={taskId} />; }
export function App() {
  return <Routes><Route element={<AppShell />}><Route index element={<Navigate to="/projects" replace />} /><Route path="operations" element={<OperationsPage />} /><Route path="projects" element={<ProjectsPage />} /><Route path="projects/:projectId" element={<ProjectRoute />} /><Route path="tasks/:taskId" element={<TaskRoute />} /><Route path="*" element={<><h1>Page not found</h1><p>This route does not exist.</p><Link to="/projects">Back to Projects</Link></>} /></Route></Routes>;
}
