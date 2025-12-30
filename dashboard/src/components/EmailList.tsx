import { format } from 'date-fns';
import type { EmailRecord, ProcessingStatus } from '../types';

interface EmailListProps {
  emails: EmailRecord[];
  loading: boolean;
  selectedId?: string;
  onSelect: (email: EmailRecord) => void;
  onRefresh: () => void;
}

const STATUS_COLORS: Record<ProcessingStatus, string> = {
  RECEIVED: '#3498db',
  DUPLICATE: '#95a5a6',
  CLASSIFYING: '#f39c12',
  NOT_ELOC: '#9b59b6',
  EXTRACTING: '#e67e22',
  PERSISTING: '#1abc9c',
  COMPLETED: '#27ae60',
  FAILED: '#e74c3c',
};

const STATUS_ICONS: Record<ProcessingStatus, string> = {
  RECEIVED: '📥',
  DUPLICATE: '🔄',
  CLASSIFYING: '🔍',
  NOT_ELOC: '❌',
  EXTRACTING: '📊',
  PERSISTING: '💾',
  COMPLETED: '✅',
  FAILED: '❗',
};

export function EmailList({ emails, loading, selectedId, onSelect, onRefresh }: EmailListProps) {
  const formatTime = (dateStr: string) => {
    try {
      return format(new Date(dateStr), 'MMM d, HH:mm');
    } catch {
      return dateStr;
    }
  };

  const getStatusStyle = (status: string) => ({
    backgroundColor: STATUS_COLORS[status as ProcessingStatus] || '#95a5a6',
    color: 'white',
  });

  if (loading && emails.length === 0) {
    return <div className="email-list loading">Loading emails...</div>;
  }

  return (
    <div className="email-list">
      <div className="email-list-header">
        <h2>Recent Emails</h2>
        <button onClick={onRefresh} className="refresh-btn" title="Refresh">
          🔄 Refresh
        </button>
      </div>

      {emails.length === 0 ? (
        <div className="empty-state">No emails processed yet</div>
      ) : (
        <div className="email-items">
          {emails.map((email) => (
            <div
              key={email.email_id}
              className={`email-item ${selectedId === email.email_id ? 'selected' : ''}`}
              onClick={() => onSelect(email)}
            >
              <div className="email-row">
                <span className="email-status" style={getStatusStyle(email.status)}>
                  {STATUS_ICONS[email.status as ProcessingStatus]} {email.status}
                </span>
                <span className="email-time">{formatTime(email.received_at)}</span>
              </div>

              <div className="email-subject" title={email.subject}>
                {email.subject || '(No subject)'}
              </div>

              <div className="email-sender">{email.sender}</div>

              {email.classification && (
                <div className="email-classification">
                  <span className={`classification-badge ${email.classification.result?.toLowerCase()}`}>
                    {email.classification.result}
                  </span>
                  {email.classification.votes && (
                    <span className="votes">
                      S:{email.classification.votes.similarity?.charAt(0) || '?'}
                      {' '}C:{email.classification.votes.claude?.charAt(0) || '?'}
                      {' '}O:{email.classification.votes.openai?.charAt(0) || '?'}
                    </span>
                  )}
                </div>
              )}

              {email.extraction && (
                <div className="email-extraction">
                  <span className="eloc-id">{email.extraction.eloc_id}</span>
                  <span className="company">{email.extraction.company_symbol}</span>
                </div>
              )}

              {email.timing?.total_ms && (
                <div className="email-timing">
                  ⏱️ {(email.timing.total_ms / 1000).toFixed(1)}s
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default EmailList;
