import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App } from './app/App';
import './styles/app.css';
import { initializeAccess } from './api/access';
const root = createRoot(document.getElementById('root')!);
void initializeAccess().then(() => root.render(<BrowserRouter><App /></BrowserRouter>))
  .catch(() => root.render(<main><h1>Access unavailable</h1><p>Refresh this page or <a href="/login">sign in again</a>. No action was retried.</p></main>));
