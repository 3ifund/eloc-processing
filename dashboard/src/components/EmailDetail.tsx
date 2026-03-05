import { useEffect, useState } from 'react';
import type { EmailRecord, LogEntry, ElocData } from '../types';
import { dashboardApi } from '../api/client';

interface EmailDetailProps {
  email: EmailRecord | null;
  logs: LogEntry[];
  loading: boolean;
  onClose: () => void;
}

export function EmailDetail({ email, logs, loading, onClose }: EmailDetailProps) {
  const [elocData, setElocData] = useState<ElocData | null>(null);
  const [elocLoading, setElocLoading] = useState(false);
  const [elocError, setElocError] = useState<string | null>(null);

  // Fetch ELOC data when email has an eloc_id
  useEffect(() => {
    const elocId = email?.extraction?.eloc_id;
    if (elocId && !elocId.includes('Not specified')) {
      setElocLoading(true);
      setElocError(null);
      dashboardApi.getElocData(elocId)
        .then(data => {
          setElocData(data);
          setElocLoading(false);
        })
        .catch(err => {
          console.error('Failed to fetch ELOC data:', err);
          setElocError(err.response?.status === 404 ? 'ELOC not found in database' : 'Failed to load ELOC data');
          setElocLoading(false);
        });
    } else {
      setElocData(null);
      setElocError(null);
    }
  }, [email?.extraction?.eloc_id]);
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
      const date = new Date(dateStr);
      // Display in Eastern time
      return date.toLocaleString('en-US', {
        timeZone: 'America/New_York',
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
      });
    } catch {
      return dateStr;
    }
  };

  // Format date-only fields (no time component)
  const formatDateOnly = (dateStr?: string) => {
    if (!dateStr) return '-';
    try {
      const date = new Date(dateStr);
      // Display just the date in Eastern time
      return date.toLocaleString('en-US', {
        timeZone: 'America/New_York',
        year: 'numeric',
        month: 'short',
        day: 'numeric'
      });
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
            {email.document_type && (
              <div className="detail-row">
                <span className="label">Document Type:</span>
                <span className={`doc-type-badge ${email.document_type.toLowerCase().replace('_', '-')}`}>
                  {email.document_type.replace('_', ' ')}
                </span>
              </div>
            )}
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
              <span className="value">{email.recipients?.join(', ') || '-'}</span>
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
            {email.status === 'NOT_RELEVANT' && email.not_relevant_reason && (
              <div className="detail-row">
                <span className="label">Skip Reason:</span>
                <span className="value warning">{email.not_relevant_reason}</span>
              </div>
            )}
          </div>
        </section>

        {/* Classification */}
        {email.classification && (
          <section className="detail-section">
            <h3>Classification (Dual LLM)</h3>
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
            </div>

            {email.classification.votes && (
              <div className="votes-detail">
                <h4>Classifier Votes</h4>
                <div className="votes-grid">
                  <div className={`vote-card ${email.classification.votes.claude?.toLowerCase()}`}>
                    <div className="vote-source">Claude</div>
                    <div className="vote-value">{email.classification.votes.claude || 'N/A'}</div>
                    {email.classification.votes.claude === 'ERROR' && email.classification.errors?.claude && (
                      <div className="vote-error">
                        <span className="error-type">{email.classification.errors.claude.error_type}</span>
                        <span className="error-message">{email.classification.errors.claude.error}</span>
                      </div>
                    )}
                  </div>
                  <div className={`vote-card ${email.classification.votes.openai?.toLowerCase()}`}>
                    <div className="vote-source">OpenAI</div>
                    <div className="vote-value">{email.classification.votes.openai || 'N/A'}</div>
                    {email.classification.votes.openai === 'ERROR' && email.classification.errors?.openai && (
                      <div className="vote-error">
                        <span className="error-type">{email.classification.errors.openai.error_type}</span>
                        <span className="error-message">{email.classification.errors.openai.error}</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </section>
        )}

        {/* Extraction - for Purchase Notices */}
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
              {email.extraction.avg_confidence !== undefined && (
                <div className="detail-row">
                  <span className="label">Avg Confidence:</span>
                  <span className={`value confidence-badge ${
                    email.extraction.avg_confidence >= 75 ? 'high' :
                    email.extraction.avg_confidence >= 50 ? 'medium' : 'low'
                  }`}>
                    {email.extraction.avg_confidence.toFixed(1)}%
                  </span>
                </div>
              )}
              {(email.extraction.ner_applicable_count !== undefined || email.extraction.llm_only_count !== undefined) && (
                <div className="detail-row">
                  <span className="label">Validation:</span>
                  <span className="value">
                    {email.extraction.ner_applicable_count !== undefined && (
                      <>NER: {email.extraction.ner_validated_count ?? 0}/{email.extraction.ner_applicable_count}</>
                    )}
                    {email.extraction.llm_only_count !== undefined && email.extraction.llm_only_count > 0 && (
                      <>{email.extraction.ner_applicable_count !== undefined && ', '}LLM-only: {email.extraction.llm_only_count}</>
                    )}
                  </span>
                </div>
              )}
              {/* Fallback for old data without new fields */}
              {email.extraction.ner_validated_count !== undefined &&
               email.extraction.ner_applicable_count === undefined && (
                <div className="detail-row">
                  <span className="label">NER Validated:</span>
                  <span className="value">
                    {email.extraction.ner_validated_count} / {email.extraction.fields_extracted} fields
                  </span>
                </div>
              )}
            </div>

            {/* Field Confidence Details */}
            {email.extraction.field_confidences && Object.keys(email.extraction.field_confidences).length > 0 && (
              <div className="confidence-details">
                <h4>Field Confidence Scores</h4>
                <div className="confidence-grid">
                  {Object.entries(email.extraction.field_confidences)
                    .sort(([, a], [, b]) => b - a)
                    .map(([field, conf]) => (
                      <div key={field} className="confidence-item">
                        <span className="field-name">{field.replace(/_/g, ' ')}</span>
                        <div className="confidence-bar-container">
                          <div
                            className={`confidence-bar ${
                              conf >= 75 ? 'high' : conf >= 50 ? 'medium' : 'low'
                            }`}
                            style={{ width: `${conf}%` }}
                          />
                          <span className="confidence-value">{conf}%</span>
                        </div>
                      </div>
                    ))
                  }
                </div>
              </div>
            )}

            {/* Persisted Extracted Field Values */}
            {elocLoading && (
              <div className="loading">Loading extracted fields from database...</div>
            )}
            {elocError && (
              <div className="error-message">{elocError}</div>
            )}
            {elocData && (
              <div className="extracted-fields-detail">
                <h4>Extracted Field Values (from MongoDB)</h4>
                <div className="extracted-fields-grid">
                  {/* Dynamically render all extracted fields with {value, confidence} pattern */}
                  {(() => {
                    // Define field display configuration
                    const fieldConfig: Record<string, {
                      label: string;
                      format?: 'date' | 'currency' | 'number' | 'boolean';
                      highlight?: boolean;
                    }> = {
                      company_symbol: { label: 'Company Symbol' },
                      company_name: { label: 'Company Name' },
                      vwap_purchase_share_amount: { label: 'Share Amount', format: 'number', highlight: true },
                      vwap_purchase_exercise_date: { label: 'Exercise Date', format: 'date' },
                      vwap_purchase_period_start_date: { label: 'Period Start', format: 'date' },
                      vwap_purchase_period_end_date: { label: 'Period End', format: 'date' },
                      vwap_purchase_settlement_date: { label: 'Settlement Date', format: 'date' },
                      aggregate_limit_available: { label: 'Aggregate Limit', format: 'currency' },
                      company_signator: { label: 'Signatory' },
                      signatory_title: { label: 'Signatory Title' },
                      agreement_date: { label: 'Agreement Date', format: 'date' },
                      purchase_notice_company_signature: { label: 'Company Signature Verified', format: 'boolean', highlight: true },
                    };

                    // Format value based on type
                    const formatValue = (value: unknown, format?: string): string => {
                      if (value === null || value === undefined) return '(not extracted)';
                      if (format === 'date') return formatDateOnly(String(value));
                      if (format === 'currency') return `$${Number(value).toLocaleString()}`;
                      if (format === 'number') return Number(value).toLocaleString();
                      if (format === 'boolean') return value ? 'TRUE' : 'FALSE';
                      return String(value);
                    };

                    // Get CSS class for boolean values
                    const getBooleanClass = (value: unknown): string => {
                      if (typeof value === 'boolean') {
                        return value ? 'success' : 'warning';
                      }
                      return '';
                    };

                    return Object.entries(fieldConfig).map(([fieldKey, config]) => {
                      // Access fields from extracted_fields nested object
                      const fieldData = elocData.extracted_fields?.[fieldKey];

                      // Show all fields, even if value is null/missing
                      const hasValue = fieldData && fieldData.value !== undefined && fieldData.value !== null;
                      const value = fieldData?.value;
                      const confidence = fieldData?.confidence;

                      return (
                        <div key={fieldKey} className={`extracted-field-row ${!hasValue ? 'missing' : ''}`}>
                          <span className="field-label">{config.label}:</span>
                          <span className={`field-value ${config.highlight ? 'highlight' : ''} ${config.format === 'boolean' ? getBooleanClass(value) : ''}`}>
                            {formatValue(value, config.format)}
                          </span>
                          <span className={`field-conf ${!hasValue ? 'missing' : confidence !== undefined && confidence < 75 ? 'low' : ''}`}>
                            {confidence !== undefined ? `${confidence.toFixed(0)}%` : '-'}
                          </span>
                        </div>
                      );
                    });
                  })()}

                  {/* Non-extracted metadata fields */}
                  {elocData.purchase_notice_filename && (
                    <div className="extracted-field-row metadata">
                      <span className="field-label">PDF Filename:</span>
                      <span className="field-value">{elocData.purchase_notice_filename}</span>
                      <span className="field-conf">-</span>
                    </div>
                  )}
                  {elocData.has_confirmation !== undefined && (
                    <div className="extracted-field-row metadata">
                      <span className="field-label">Confirmation:</span>
                      <span className={`field-value ${elocData.has_confirmation ? 'success' : ''}`}>
                        {elocData.has_confirmation
                          ? `Matched - ${elocData.countersigned_purchase_confirmation_filename}`
                          : 'Not yet received'}
                      </span>
                      <span className="field-conf">-</span>
                    </div>
                  )}
                </div>
              </div>
            )}
          </section>
        )}

        {/* Signature Verification - for Purchase Confirmations */}
        {email.signature_verification && (
          <section className="detail-section">
            <h3>Signature Verification (Dual LLM)</h3>
            <div className="detail-grid">
              <div className="detail-row">
                <span className="label">Company Signed:</span>
                <span className={`value ${email.signature_verification.company_signed ? 'success' : 'warning'}`}>
                  {email.signature_verification.company_signed ? 'Yes' : 'No'}
                  {email.signature_verification.company_signatory && (
                    <span className="signatory"> ({email.signature_verification.company_signatory})</span>
                  )}
                </span>
              </div>
              <div className="detail-row">
                <span className="label">Investor Signed:</span>
                <span className={`value ${email.signature_verification.investor_signed ? 'success' : 'warning'}`}>
                  {email.signature_verification.investor_signed ? 'Yes' : 'No'}
                  {email.signature_verification.investor_signatory && (
                    <span className="signatory"> ({email.signature_verification.investor_signatory})</span>
                  )}
                </span>
              </div>
              <div className="detail-row">
                <span className="label">Both Parties Signed:</span>
                <span className={`value ${email.signature_verification.both_signed ? 'success' : 'error'}`}>
                  {email.signature_verification.both_signed ? 'Yes - Complete' : 'No - Incomplete'}
                </span>
              </div>
              {email.signature_verification.llm_agreement !== undefined && (
                <div className="detail-row">
                  <span className="label">LLM Agreement:</span>
                  <span className={`value ${email.signature_verification.llm_agreement ? 'success' : 'warning'}`}>
                    {email.signature_verification.llm_agreement ? 'Claude + OpenAI Agree' : 'Disagreement'}
                  </span>
                </div>
              )}
              {email.signature_verification.agreement_details && (
                <div className="detail-row">
                  <span className="label">Fields Agreement:</span>
                  <span className="value">
                    {email.signature_verification.agreement_details.fields_agreed ?? 0}/
                    {email.signature_verification.agreement_details.total_fields ?? 0} fields
                    ({((email.signature_verification.agreement_details.agreement_rate ?? 0) * 100).toFixed(0)}%)
                  </span>
                </div>
              )}
              {email.signature_verification.notes && (
                <div className="detail-row">
                  <span className="label">Notes:</span>
                  <span className="value">{email.signature_verification.notes}</span>
                </div>
              )}
            </div>

            {/* Confirmation Extracted Field Values from MongoDB */}
            {elocLoading && (
              <div className="loading">Loading confirmation data from database...</div>
            )}
            {elocError && (
              <div className="error-message">{elocError}</div>
            )}
            {elocData?.countersigned_purchase_confirmation_signature_verification && (
              <div className="extracted-fields-detail">
                <h4>Confirmation Extracted Fields (from MongoDB)</h4>
                <div className="extracted-fields-grid">
                  {(() => {
                    const sigVerif = elocData.countersigned_purchase_confirmation_signature_verification;

                    const fieldConfig: Array<{
                      key: keyof typeof sigVerif;
                      label: string;
                      format?: 'date' | 'number' | 'boolean';
                      highlight?: boolean;
                    }> = [
                      { key: 'companySignaturePresent', label: 'COMPANY COUNTERSIGNED', format: 'boolean', highlight: true },
                      { key: 'firmSignaturePresent', label: 'Investor Signed', format: 'boolean', highlight: true },
                      { key: 'bothPartiesSigned', label: 'Both Parties Signed', format: 'boolean', highlight: true },
                      { key: 'targetCompany', label: 'Target Company' },
                      { key: 'investorCompany', label: 'Investor Company' },
                      { key: 'shareAmount', label: 'Share Amount', format: 'number' },
                      { key: 'exerciseDate', label: 'Exercise Date', format: 'date' },
                      { key: 'companySignatory', label: 'Company Signatory' },
                      { key: 'firmSignatory', label: 'Investor Signatory' },
                      { key: 'verificationNotes', label: 'Verification Notes' },
                    ];

                    const formatValue = (value: unknown, format?: string): string => {
                      if (value === null || value === undefined) return '(not extracted)';
                      if (format === 'date') return formatDateOnly(String(value));
                      if (format === 'number') return Number(value).toLocaleString();
                      if (format === 'boolean') return value ? 'TRUE' : 'FALSE';
                      return String(value);
                    };

                    const getBooleanClass = (value: unknown): string => {
                      if (typeof value === 'boolean') {
                        return value ? 'success' : 'warning';
                      }
                      return '';
                    };

                    // Get per-field confidence scores
                    const fieldConfidences = sigVerif.fieldConfidences || {};

                    return fieldConfig.map(({ key, label, format, highlight }) => {
                      const value = sigVerif[key];
                      const hasValue = value !== undefined && value !== null;

                      // Get confidence for this field
                      const confidence = fieldConfidences[key];
                      const confidenceDisplay = confidence !== undefined ? `${confidence.toFixed(0)}%` : '-';
                      const confidenceClass = confidence !== undefined && confidence < 100 ? 'low' : '';

                      return (
                        <div key={key} className={`extracted-field-row ${!hasValue ? 'missing' : ''}`}>
                          <span className="field-label">{label}:</span>
                          <span className={`field-value ${highlight ? 'highlight' : ''} ${format === 'boolean' ? getBooleanClass(value) : ''}`}>
                            {formatValue(value, format)}
                          </span>
                          <span className={`field-conf ${confidenceClass}`}>{confidenceDisplay}</span>
                        </div>
                      );
                    });
                  })()}

                  {/* Confirmation PDF filename */}
                  {elocData.countersigned_purchase_confirmation_filename && (
                    <div className="extracted-field-row metadata">
                      <span className="field-label">PDF Filename:</span>
                      <span className="field-value">{elocData.countersigned_purchase_confirmation_filename}</span>
                      <span className="field-conf">-</span>
                    </div>
                  )}
                </div>
              </div>
            )}
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
              {email.timing.extraction_ms !== undefined && (
                <div className="detail-row">
                  <span className="label">Extraction:</span>
                  <span className="value">{formatMs(email.timing.extraction_ms)}</span>
                </div>
              )}
              {email.timing.verification_ms !== undefined && (
                <div className="detail-row">
                  <span className="label">Verification:</span>
                  <span className="value">{formatMs(email.timing.verification_ms)}</span>
                </div>
              )}
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
                    {new Date(log.timestamp).toLocaleString('en-US', {
                      timeZone: 'America/New_York',
                      hour: '2-digit',
                      minute: '2-digit',
                      second: '2-digit',
                      hour12: false
                    })}
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
