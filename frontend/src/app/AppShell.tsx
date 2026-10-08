import { NavLink, Outlet } from 'react-router-dom';
import { EnvironmentNotice } from '../components/EnvironmentNotice';
import { hostedAccess, logout } from '../api/access';
import { useState } from 'react';
export function AppShell() {
  const [signingOut, setSigningOut] = useState(false);
  const [accessError, setAccessError] = useState(false);
  async function signOut() {
    setSigningOut(true); setAccessError(false);
    try { await logout(); } catch { setAccessError(true); setSigningOut(false); }
  }
  return <div className="shell"><a className="skip-link" href="#main-content">Skip to content</a>
    <header className="topbar"><NavLink to="/projects" className="brand"><span className="brand-mark" aria-hidden="true">Q</span>Agentic QA Orchestrator</NavLink><EnvironmentNotice mode={hostedAccess() ? 'hosted-demo' : undefined} />{hostedAccess() && <button disabled={signingOut} onClick={() => void signOut()}>Sign out</button>}{accessError && <span role="alert">Unable to sign out. Try again.</span>}</header>
    <aside className="sidebar"><p className="nav-label">WORKSPACE</p><nav aria-label="Primary"><NavLink to="/projects">Projects</NavLink></nav><p className="nav-label">OPERATIONS / LEGACY</p><nav aria-label="Operational"><NavLink to="/operations">Operations</NavLink></nav><p className="sidebar-note">Agents reason.<br />Evidence records reality.</p></aside>
    <main id="main-content" tabIndex={-1}><Outlet /></main>
  </div>;
}
