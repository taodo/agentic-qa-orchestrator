import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { EnvironmentNotice } from '../components/EnvironmentNotice';
import { hostedAccess, logout } from '../api/access';
import { useState } from 'react';
import { ThemeControl } from './ThemeControl';
import { WorkspaceContext, type WorkspaceContextValue } from './WorkspaceContext';
export function AppShell() {
  const [navigationOpen, setNavigationOpen] = useState(true);
  const [context, setContext] = useState<WorkspaceContextValue>();
  const location = useLocation();
  const projectPath = context ? `/projects/${encodeURIComponent(context.projectId)}` : '';
  const campaignPath = context?.campaignId ? `${projectPath}/campaigns/${encodeURIComponent(context.campaignId)}` : '';
  const inCampaign = !!campaignPath && (location.pathname === campaignPath || location.pathname.startsWith(campaignPath+'/'));
  const inProject = !!projectPath && (location.pathname === projectPath || location.pathname.startsWith(projectPath+'/') || inCampaign);
  const [signingOut, setSigningOut] = useState(false);
  const [accessError, setAccessError] = useState(false);
  async function signOut() {
    setSigningOut(true); setAccessError(false);
    try { await logout(); } catch { setAccessError(true); setSigningOut(false); }
  }
  return <WorkspaceContext.Provider value={setContext}><div className="shell"><a className="skip-link" href="#main-content">Skip to content</a>
    <header className="topbar"><button className="sidebar-toggle" aria-controls="workspace-sidebar" aria-expanded={navigationOpen} onClick={()=>setNavigationOpen(value=>!value)}>Navigation</button><NavLink to="/projects" className="brand"><span className="brand-mark" aria-hidden="true">Q</span>Agentic QA Orchestrator</NavLink><EnvironmentNotice mode={hostedAccess() ? 'hosted-demo' : undefined} />{hostedAccess() && <button disabled={signingOut} onClick={() => void signOut()}>Sign out</button>}{accessError && <span role="alert">Unable to sign out. Try again.</span>}</header>
    <aside id="workspace-sidebar" data-collapsed={!navigationOpen} className="sidebar" aria-label="Workspace navigation"><p className="nav-label">Workspace</p><nav aria-label="Primary"><NavLink to="/projects">Projects</NavLink></nav>{inProject && <div className="workspace-context"><span className="nav-label">Project</span><NavLink to={projectPath} end title={`Project ID: ${context?.projectId}`}>Project workspaces</NavLink></div>}
      {inCampaign && <><div className="campaign-context"><span className="nav-label">QA workflow</span><p title={context?.campaignName}>{context?.campaignName}</p></div>
        {context?.target && <div className="sidebar-target"><span className="nav-label" title="Current Campaign configuration; historical Runs retain their saved Target">Campaign Target</span><strong>{context.target.name}</strong><p>{context.target.type} · {context.target.environment}</p></div>}
        <nav aria-label="Campaign preparation" className="campaign-navigation">
          <NavLink to={campaignPath} end>Overview</NavLink>
          <NavLink to={campaignPath+'/specification'}>Specification</NavLink>
          <NavLink to={campaignPath+'/test-design'}>Test Design</NavLink>
          <NavLink to={campaignPath+'/execution'}>Execution</NavLink>
          {location.pathname.startsWith(campaignPath+'/runs')?<Link aria-current="page" to={campaignPath+'/results'}>Results</Link>:<NavLink to={campaignPath+'/results'}>Results</NavLink>}
          <NavLink to={projectPath+'/settings'}>Project Settings</NavLink>
          <NavLink to={campaignPath+'/audit'}>Advanced / Audit</NavLink>
        </nav></>}
      <p className="nav-label secondary-nav-label">More</p><nav aria-label="Operational"><NavLink to="/operations">Operations</NavLink></nav><p className="sidebar-note">Agents reason.<br />Evidence records reality.</p><ThemeControl/></aside>
    <main id="main-content" tabIndex={-1}><Outlet /></main>
  </div></WorkspaceContext.Provider>;
}
