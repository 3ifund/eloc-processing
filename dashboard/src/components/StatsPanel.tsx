import type { Stats } from '../types';

interface StatsPanelProps {
  stats: Stats | null;
  loading: boolean;
}

export function StatsPanel({ stats, loading }: StatsPanelProps) {
  if (loading) {
    return <div className="stats-panel loading">Loading statistics...</div>;
  }

  if (!stats) {
    return <div className="stats-panel error">Failed to load statistics</div>;
  }

  const formatMs = (ms?: number) => {
    if (!ms) return '-';
    if (ms < 1000) return `${Math.round(ms)}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  return (
    <div className="stats-panel">
      <h2>Processing Statistics</h2>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-value">{stats.total_emails}</div>
          <div className="stat-label">Total Emails</div>
        </div>

        <div className="stat-card">
          <div className="stat-value">{stats.today_emails}</div>
          <div className="stat-label">Today</div>
        </div>

        <div className="stat-card">
          <div className="stat-value">{stats.status_counts.COMPLETED || 0}</div>
          <div className="stat-label">Completed</div>
        </div>

        <div className="stat-card">
          <div className="stat-value">{stats.status_counts.FAILED || 0}</div>
          <div className="stat-label">Failed</div>
        </div>
      </div>

      <div className="stats-details">
        <div className="stats-section">
          <h3>Classification Results</h3>
          <div className="stat-row">
            <span className="label">ELOC:</span>
            <span className="value">{stats.classification_counts.ELOC || 0}</span>
          </div>
          <div className="stat-row">
            <span className="label">NOT_ELOC:</span>
            <span className="value">{stats.classification_counts.NOT_ELOC || 0}</span>
          </div>
        </div>

        <div className="stats-section">
          <h3>Classifier Agreement</h3>
          <div className="stat-row">
            <span className="label">Unanimous:</span>
            <span className="value">{stats.agreement_counts.unanimous || 0}</span>
          </div>
          <div className="stat-row">
            <span className="label">Majority:</span>
            <span className="value">{stats.agreement_counts.majority || 0}</span>
          </div>
          <div className="stat-row">
            <span className="label">Split:</span>
            <span className="value">{stats.agreement_counts.split || 0}</span>
          </div>
        </div>

        <div className="stats-section">
          <h3>Average Timing</h3>
          <div className="stat-row">
            <span className="label">Classification:</span>
            <span className="value">{formatMs(stats.avg_timing.classification_ms)}</span>
          </div>
          <div className="stat-row">
            <span className="label">Extraction:</span>
            <span className="value">{formatMs(stats.avg_timing.extraction_ms)}</span>
          </div>
          <div className="stat-row">
            <span className="label">Total:</span>
            <span className="value">{formatMs(stats.avg_timing.total_ms)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default StatsPanel;
