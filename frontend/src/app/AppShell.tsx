import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { EnvironmentNotice } from '../components/EnvironmentNotice';
import { hostedAccess, logout } from '../api/access';
import { useState } from 'react';
import { WorkspaceContext, type WorkspaceContextValue } from './WorkspaceContext';
export function AppShell() {
  const [context, setContext] = useState<WorkspaceContextValue>();
  const location = useLocation();
  const projectPath = context ? `/projects/${encodeURIComponent(context.projectId)}` : '';
  const campaignPath = context?.campaignId ? `${projectPath}/campaigns/${encodeURIComponent(context.campaignId)}` : '';
  const inCampaign = !!campaignPath && (location.pathname === campaignPath || location.pathname.startsWith(campaignPath+'/'));
  const inProject = !!projectPath && (location.pathname === projectPath || inCampaign);
  const [signingOut, setSigningOut] = useState(false);
  const [accessError, setAccessError] = useState(false);
  async function signOut() {
    setSigningOut(true); setAccessError(false);
    try { await logout(); } catch { setAccessError(true); setSigningOut(false); }
  }
  return <WorkspaceContext.Provider value={setContext}><div className="shell"><a className="skip-link" href="#main-content">Skip to content</a>
    <header className="topbar"><NavLink to="/projects" className="brand"><span className="brand-mark" aria-hidden="true">Q</span>Agentic QA Orchestrator</NavLink><EnvironmentNotice mode={hostedAccess() ? 'hosted-demo' : undefined} />{hostedAccess() && <button disabled={signingOut} onClick={() => void signOut()}>Sign out</button>}{accessError && <span role="alert">Unable to sign out. Try again.</span>}</header>
    <aside className="sidebar" aria-label="Workspace navigation"><p className="nav-label">WORKSPACE</p><nav aria-label="Primary"><NavLink to="/projects">Projects</NavLink></nav>{inProject && <div className="workspace-context"><span className="nav-label">PROJECT CONTEXT</span><NavLink to={projectPath} end>Project Campaigns<span className="context-id">{context?.projectId}</span></NavLink></div>}
      {inCampaign && <><div className="campaign-context"><span className="nav-label">CAMPAIGN</span><p title={context?.campaignName}>{context?.campaignName}</p></div>
        <nav aria-label="Campaign preparation" className="campaign-navigation">
          <NavLink to={campaignPath} end>Overview</NavLink>
          <p className="nav-label">PREPARATION</p>
          <NavLink to={campaignPath+'/requirements'}>Requirements</NavLink>
          <NavLink to={campaignPath+'/test-specifications'}>Test Cases</NavLink>
          <NavLink to={campaignPath+'/traceability'}>Traceability</NavLink>
          <NavLink to={campaignPath+'/readiness'}>Readiness</NavLink>
          <p className="nav-label">EXECUTION</p><NavLink to={campaignPath+'/runs'}>Runs</NavLink>
        </nav></>}
      <p className="nav-label secondary-nav-label">OPERATIONS / LEGACY</p><nav aria-label="Operational"><NavLink to="/operations">Operations</NavLink></nav><p className="sidebar-note">Agents reason.<br />Evidence records reality.</p></aside>
    <main id="main-content" tabIndex={-1}><Outlet /></main>
  </div></WorkspaceContext.Provider>;
}
