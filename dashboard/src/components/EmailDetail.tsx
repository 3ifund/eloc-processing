import { format } from 'date-fns';
import type { EmailRecord, LogEntry } from '../types';

interface EmailDetailProps {
  email: EmailRecord | null;
  logs: LogEntry[];
  loading: boolean;
  onClose: () => void;
}

export function EmailDetail({ email, logs, loading, onClose }: EmailDetailProps) {
  if (!email) {
    return (
      <div className="email-detail empty">
        <p>Select an email to view details</p>
      </div>
    );
  }

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return '-';
    try {
      return format(new Date(dateStr), 'MMM d, yyyy HH:mm:ss');
    } catch {
      return dateStr;
    }
  };

  const formatMs = (ms?: number) => {
    if (!ms) return '-';
    if (ms < 1000) return `${Math.round(ms)}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
  };

  return (
    <div className="email-detail">
      <div className="detail-header">
        <h2>Email Details</h2>
        <button onClick={onClose} className="close-btn">×</button>
      </div>

      <div className="detail-content">
        {/* Basic Info */}
        <section className="detail-section">
          <h3>Email Information</h3>
          <div className="detail-grid">
            <div className="detail-row">
              <span className="label">Status:</span>
              <span className={`status-badge ${email.status.toLowerCase()}`}>{email.status}</span>
            </div>
            <div className="detail-row">
              <span className="label">Subject:</span>
              <span className="value">{email.subject}</span>
            </div>
            <div className="detail-row">
              <span className="label">From:</span>
              <span className="value">{email.sender}</span>
            </div>
            <div className="detail-row">
              <span className="label">To:</span>
              <span className="value">{email.recipients.join(', ')}</span>
            </div>
            <div className="detail-row">
              <span className="label">Received:</span>
              <span className="value">{formatDate(email.received_at)}</span>
            </div>
            <div className="detail-row">
              <span className="label">Attachments:</span>
              <span className="value">{email.attachment_count} file(s)</span>
            </div>
            {email.is_duplicate && (
              <div className="detail-row">
                <span className="label">Duplicate:</span>
                <span className="value warning">Yes (skipped)</span>
              </div>
            )}
          </div>
        </section>

        {/* Classification */}
        {email.classification && (
          <section className="detail-section">
            <h3>Classification (Triple Classifier)</h3>
            <div className="detail-grid">
              <div className="detail-row">
                <span className="label">Result:</span>
                <span className={`classification-result ${email.classification.result?.toLowerCase()}`}>
                  {email.classification.result}
                </span>
              </div>
              <div className="detail-row">
                <span className="label">Confidence:</span>
                <span className="value">{email.classification.confidence}</span>
              </div>
              <div className="detail-row">
                <span className="label">Agreement:</span>
                <span className="value">{email.classification.agreement}</span>
              </div>
              {email.classification.similarity_score !== undefined && (
                <div className="detail-row">
                  <span className="label">Similarity Score:</span>
                  <span className="value">{email.classification.similarity_score.toFixed(3)}</span>
                </div>
              )}
            </div>

            {email.classification.votes && (
              <div className="votes-detail">
                <h4>Classifier Votes</h4>
                <div className="votes-grid">
                  <div className={`vote-card ${email.classification.votes.similarity?.toLowerCase()}`}>
                    <div className="vote-source">Similarity</div>
                    <div className="vote-value">{email.classification.votes.similarity || 'N/A'}</div>
                  </div>
                  <div className={`vote-card ${email.classification.votes.claude?.toLowerCase()}`}>
                    <div className="vote-source">Claude</div>
                    <div className="vote-value">{email.classification.votes.claude || 'N/A'}</div>
                  </div>
                  <div className={`vote-card ${email.classification.votes.openai?.toLowerCase()}`}>
                    <div className="vote-source">OpenAI</div>
                    <div className="vote-value">{email.classification.votes.openai || 'N/A'}</div>
                  </div>
                </div>
              </div>
            )}
          </section>
        )}

        {/* Extraction */}
        {email.extraction && (
          <section className="detail-section">
            <h3>Extraction Results</h3>
            <div className="detail-grid">
              <div className="detail-row">
                <span className="label">ELOC ID:</span>
                <span className="value eloc-id">{email.extraction.eloc_id}</span>
              </div>
              <div className="detail-row">
                <span className="label">Company:</span>
                <span className="value">
                  {email.extraction.company_name} ({email.extraction.company_symbol})
                </span>
              </div>
              <div className="detail-row">
                <span className="label">Fields Extracted:</span>
                <span className="value">{email.extraction.fields_extracted}</span>
              </div>
              {email.extraction.market_data_date && (
                <div className="detail-row">
                  <span className="label">Market Data Date:</span>
                  <span className="value">{formatDate(email.extraction.market_data_date)}</span>
                </div>
              )}
            </div>
          </section>
        )}

        {/* Timing */}
        {email.timing && (
          <section className="detail-section">
            <h3>Processing Timing</h3>
            <div className="detail-grid">
              <div className="detail-row">
                <span className="label">Started:</span>
                <span className="value">{formatDate(email.timing.started_at)}</span>
              </div>
              <div className="detail-row">
                <span className="label">Classification:</span>
                <span className="value">{formatMs(email.timing.classification_ms)}</span>
              </div>
              <div className="detail-row">
                <span className="label">Extraction:</span>
                <span className="value">{formatMs(email.timing.extraction_ms)}</span>
              </div>
              <div className="detail-row">
                <span className="label">Total:</span>
                <span className="value highlight">{formatMs(email.timing.total_ms)}</span>
              </div>
              <div className="detail-row">
                <span className="label">Completed:</span>
                <span className="value">{formatDate(email.timing.completed_at)}</span>
              </div>
            </div>
          </section>
        )}

        {/* Error */}
        {email.error && (
          <section className="detail-section error-section">
            <h3>Error Details</h3>
            <div className="error-content">
              <div className="detail-row">
                <span className="label">Stage:</span>
                <span className="value">{email.error.stage || 'Unknown'}</span>
              </div>
              <div className="detail-row">
                <span className="label">Message:</span>
                <span className="value error">{email.error.message}</span>
              </div>
              <div className="detail-row">
                <span className="label">Time:</span>
                <span className="value">{formatDate(email.error.occurred_at)}</span>
              </div>
            </div>
          </section>
        )}

        {/* Logs */}
        <section className="detail-section">
          <h3>Processing Logs</h3>
          {loading ? (
            <div className="loading">Loading logs...</div>
          ) : logs.length === 0 ? (
            <div className="empty-logs">No logs available</div>
          ) : (
            <div className="logs-list">
              {logs.map((log, index) => (
                <div key={index} className={`log-entry ${log.level.toLowerCase()}`}>
                  <span className="log-time">
                    {format(new Date(log.timestamp), 'HH:mm:ss.SSS')}
                  </span>
                  <span className={`log-level ${log.level.toLowerCase()}`}>{log.level}</span>
                  <span className="log-category">{log.category}</span>
                  <span className="log-message">{log.message}</span>
                  {log.duration_ms && (
                    <span className="log-duration">{log.duration_ms}ms</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

export default EmailDetail;
