import { createRoot } from 'react-dom/client';
import App from './components/layout/App.jsx';
import ErrorBoundary from './components/ErrorBoundary.jsx';
import './styles.css';
import './styles/physical.css';
import PhysicalApp from './physical/PhysicalApp.jsx';
const legacy = new URLSearchParams(window.location.search).get('scene') === 'legacy';

const app = document.getElementById('root');

createRoot(app).render(
  <ErrorBoundary>
    {legacy ? <><App /><div className="legacyNotice">Иллюстративная раскладка: не положения на дату.<a href="/">Проверенные положения</a></div></> : <PhysicalApp />}
  </ErrorBoundary>,
);
