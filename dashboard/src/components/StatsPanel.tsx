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
          <h3>Document Types</h3>
          <div className="stat-row">
            <span className="label">Purchase Notice:</span>
            <span className="value">{stats.document_type_counts?.PURCHASE_NOTICE || 0}</span>
          </div>
          <div className="stat-row">
            <span className="label">Purchase Confirmation:</span>
            <span className="value">{stats.document_type_counts?.PURCHASE_CONFIRMATION || 0}</span>
          </div>
          <div className="stat-row">
            <span className="label">Not Relevant:</span>
            <span className="value">{stats.document_type_counts?.NOT_RELEVANT || 0}</span>
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
            <span className="label">Verification:</span>
            <span className="value">{formatMs(stats.avg_timing.verification_ms)}</span>
          </div>
          <div className="stat-row">
            <span className="label">Total:</span>
            <span className="value">{formatMs(stats.avg_timing.total_ms)}</span>
          </div>
        </div>

        {/* Signature Verification Stats (Purchase Confirmations) */}
        {stats.signature_verification_counts && Object.keys(stats.signature_verification_counts).length > 0 && (
          <div className="stats-section">
            <h3>Signature Verification</h3>
            <div className="stat-row">
              <span className="label">Both Signed:</span>
              <span className="value success">{stats.signature_verification_counts.both_signed || 0}</span>
            </div>
            <div className="stat-row">
              <span className="label">Investor Only:</span>
              <span className="value">{stats.signature_verification_counts.investor_only || 0}</span>
            </div>
            <div className="stat-row">
              <span className="label">Company Only:</span>
              <span className="value">{stats.signature_verification_counts.company_only || 0}</span>
            </div>
            <div className="stat-row">
              <span className="label">Neither:</span>
              <span className="value warning">{stats.signature_verification_counts.neither || 0}</span>
            </div>
          </div>
        )}

        {/* Signature LLM Agreement */}
        {stats.signature_llm_agreement_counts && Object.keys(stats.signature_llm_agreement_counts).length > 0 && (
          <div className="stats-section">
            <h3>Signature LLM Agreement</h3>
            <div className="stat-row">
              <span className="label">Claude + OpenAI Agree:</span>
              <span className="value success">{stats.signature_llm_agreement_counts.agree || 0}</span>
            </div>
            <div className="stat-row">
              <span className="label">Disagree:</span>
              <span className="value warning">{stats.signature_llm_agreement_counts.disagree || 0}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default StatsPanel;
