import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './components/layout/App.jsx';
import ErrorBoundary from './components/ErrorBoundary.jsx';
import './styles.css';

const app = document.getElementById('root');

createRoot(app).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>,
);
