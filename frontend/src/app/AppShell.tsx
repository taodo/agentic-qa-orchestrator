import { NavLink, Outlet } from 'react-router-dom';
export function AppShell() {
  return <div className="shell"><a className="skip-link" href="#main-content">Skip to content</a>
    <header className="topbar"><NavLink to="/projects" className="brand"><span className="brand-mark" aria-hidden="true">Q</span>QA Sentinel</NavLink><span className="environment">Local operator workspace</span></header>
    <aside className="sidebar"><p className="nav-label">WORKSPACE</p><nav aria-label="Primary"><NavLink to="/projects">Projects</NavLink></nav><p className="sidebar-note">Agents reason.<br />Evidence records reality.</p></aside>
    <main id="main-content" tabIndex={-1}><Outlet /></main>
  </div>;
}
