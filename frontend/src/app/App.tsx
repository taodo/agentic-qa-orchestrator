import { SpecificationPage, TestDesignPage, ExecutionPage, ResultsPage, ProductOverviewPage, AuditPage } from '../pages/ProductV2';
import { Navigate, Routes, Route, useParams, Link } from 'react-router-dom';
import { CampaignRunsPage, CampaignRunDetailPage } from '../pages/CampaignRunsPage';
import { AppShell } from './AppShell';
import { ProjectsPage } from '../pages/ProjectsPage';
import { ProjectDetailPage, ProjectSettingsPage } from '../pages/ProjectDetailPage';
import { TaskDetailPage } from '../pages/TaskDetailPage';
import { OperationsPage } from '../pages/OperationsPage';
import { CampaignDetailPage, CampaignRequirementsPage, CampaignTestsPage, CampaignTraceabilityPage, CampaignReadinessPage } from '../pages/CampaignDetailPage';
function ProjectRoute() { const { projectId = '' } = useParams(); return <ProjectDetailPage key={projectId} projectId={projectId} />; }
function ProjectSettingsRoute() { const { projectId = '' } = useParams(); return <ProjectSettingsPage key={projectId} projectId={projectId} />; }
function TaskRoute() { const { taskId = '' } = useParams(); return <TaskDetailPage key={taskId} taskId={taskId} />; }
function CampaignRoute() { const { projectId = '', campaignId = '' } = useParams(); return <CampaignDetailPage key={`${projectId}:${campaignId}`} projectId={projectId} campaignId={campaignId} />; }
export function App() {
  return <Routes><Route element={<AppShell />}><Route index element={<Navigate to="/projects" replace />} /><Route path="operations" element={<OperationsPage />} /><Route path="projects" element={<ProjectsPage />} /><Route path="projects/:projectId/settings" element={<ProjectSettingsRoute />} /><Route path="projects/:projectId" element={<ProjectRoute />} /><Route path="projects/:projectId/campaigns/:campaignId" element={<CampaignRoute />}>
    <Route path="runs" element={<CampaignRunsPage />} /><Route path="runs/:runId" element={<CampaignRunDetailPage />} />
    <Route index element={<ProductOverviewPage />} /><Route path="specification" element={<SpecificationPage />} /><Route path="test-design" element={<TestDesignPage />} /><Route path="execution" element={<ExecutionPage />} /><Route path="results" element={<ResultsPage />} /><Route path="audit" element={<AuditPage />} /><Route path="requirements" element={<CampaignRequirementsPage />} />
    <Route path="test-specifications" element={<CampaignTestsPage />} /><Route path="traceability" element={<CampaignTraceabilityPage />} /><Route path="readiness" element={<CampaignReadinessPage />} />
  </Route><Route path="tasks/:taskId" element={<TaskRoute />} /><Route path="*" element={<><h1>Page not found</h1><p>This route does not exist.</p><Link to="/projects">Back to Projects</Link></>} /></Route></Routes>;
}
