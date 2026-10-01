import React from 'react';

/** Last-resort guard around the whole app.
 *
 * Every scene-building and rendering error above this point is recoverable or
 * invisible; one that escapes a component render, however, unmounts the entire
 * tree and leaves a blank page with no explanation. This turns that into a
 * readable message instead of a white screen.
 */
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('Astroverse render error:', error, info?.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div style={{
        height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '40px', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
      }}>
        <div style={{ maxWidth: '760px' }}>
          <h2 style={{ color: '#ff8080', margin: '0 0 12px' }}>Приложение упало при отрисовке</h2>
          <p style={{ color: '#9aa5bd', fontSize: '13px', lineHeight: 1.6 }}>
            Сообщение об ошибке выведено в консоль браузера. Обновите страницу, чтобы
            пересобрать сцену.
          </p>
          <pre style={{
            marginTop: '16px', padding: '14px', borderRadius: '8px', overflow: 'auto',
            background: 'rgba(255,255,255,0.04)', color: '#d7dcea', fontSize: '12px',
            whiteSpace: 'pre-wrap',
          }}>
            {this.state.error.name}: {this.state.error.message}
          </pre>
        </div>
      </div>
    );
  }
}

export default ErrorBoundary;
