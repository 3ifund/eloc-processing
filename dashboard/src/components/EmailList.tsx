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
  NOT_RELEVANT: '#9b59b6',
  EXTRACTING: '#e67e22',
  VERIFYING_SIGNATURES: '#16a085',
  PERSISTING: '#1abc9c',
  COMPLETED: '#27ae60',
  FAILED: '#e74c3c',
};

const STATUS_ICONS: Record<ProcessingStatus, string> = {
  RECEIVED: '📥',
  DUPLICATE: '🔄',
  CLASSIFYING: '🔍',
  NOT_RELEVANT: '❌',
  EXTRACTING: '📊',
  VERIFYING_SIGNATURES: '✍️',
  PERSISTING: '💾',
  COMPLETED: '✅',
  FAILED: '❗',
};

const DOC_TYPE_LABELS: Record<string, string> = {
  PURCHASE_NOTICE: 'Notice',
  PURCHASE_CONFIRMATION: 'Confirmation',
  NOT_RELEVANT: 'N/A',
};

const DOC_TYPE_COLORS: Record<string, string> = {
  PURCHASE_NOTICE: '#2980b9',
  PURCHASE_CONFIRMATION: '#8e44ad',
  NOT_RELEVANT: '#7f8c8d',
};

export function EmailList({ emails, loading, selectedId, onSelect, onRefresh }: EmailListProps) {
  const formatTime = (dateStr: string) => {
    try {
      // Display in Eastern time
      return new Date(dateStr).toLocaleString('en-US', {
        timeZone: 'America/New_York',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
      });
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

              {email.document_type && (
                <div className="email-doc-type">
                  <span
                    className="doc-type-badge"
                    style={{ backgroundColor: DOC_TYPE_COLORS[email.document_type] || '#7f8c8d' }}
                  >
                    {DOC_TYPE_LABELS[email.document_type] || email.document_type}
                  </span>
                  {email.classification?.votes && (
                    <span className="votes">
                      S:{email.classification.votes.similarity?.substring(0, 2) || '?'}
                      {' '}C:{email.classification.votes.claude?.substring(0, 2) || '?'}
                      {' '}O:{email.classification.votes.openai?.substring(0, 2) || '?'}
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

              {email.signature_verification && (
                <div className="email-signatures">
                  <span className={`sig-badge ${email.signature_verification.both_signed ? 'both' : 'partial'}`}>
                    {email.signature_verification.both_signed ? '✓ Both Signed' : 'Partial'}
                  </span>
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
