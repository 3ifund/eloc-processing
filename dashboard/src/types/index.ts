// Dashboard Types

export interface ClassificationVotes {
  similarity?: string;
  claude?: string;
  openai?: string;
}

export interface ClassificationResult {
  result?: string;
  votes?: ClassificationVotes;
  agreement?: string;
  confidence?: string;
  similarity_score?: number;
}

export interface ExtractionResult {
  eloc_id?: string;
  company_symbol?: string;
  company_name?: string;
  fields_extracted?: number;
  market_data_date?: string;
  field_confidences?: Record<string, number>;  // field_name -> confidence (0-100)
  avg_confidence?: number;
  ner_validated_count?: number;
}

export interface SignatureVerificationResult {
  company_signed: boolean;
  investor_signed: boolean;
  both_signed: boolean;
  company_signatory?: string;
  investor_signatory?: string;
  notes?: string;
}

export interface TimingInfo {
  started_at?: string;
  classification_ms?: number;
  extraction_ms?: number;
  verification_ms?: number;
  total_ms?: number;
  completed_at?: string;
}

export interface ErrorInfo {
  message: string;
  stage?: string;
  occurred_at?: string;
}

export interface EmailRecord {
  email_id: string;
  internet_message_id?: string;
  subject: string;
  sender: string;
  recipients: string[];
  received_at: string;
  status: string;
  document_type?: string;  // PURCHASE_NOTICE, PURCHASE_CONFIRMATION, NOT_RELEVANT
  is_duplicate: boolean;
  has_attachments: boolean;
  attachment_count: number;
  classification?: ClassificationResult;
  extraction?: ExtractionResult;
  signature_verification?: SignatureVerificationResult;
  timing?: TimingInfo;
  error?: ErrorInfo;
}

export interface Stats {
  total_emails: number;
  today_emails: number;
  status_counts: Record<string, number>;
  document_type_counts: Record<string, number>;
  classification_counts: Record<string, number>;
  agreement_counts: Record<string, number>;
  avg_timing: {
    total_ms?: number;
    classification_ms?: number;
    extraction_ms?: number;
    verification_ms?: number;
  };
}

export interface LogEntry {
  timestamp: string;
  level: string;
  message: string;
  email_id?: string;
  category?: string;
  data?: Record<string, unknown>;
  duration_ms?: number;
}

export type ProcessingStatus =
  | 'RECEIVED'
  | 'DUPLICATE'
  | 'CLASSIFYING'
  | 'NOT_RELEVANT'
  | 'EXTRACTING'
  | 'VERIFYING_SIGNATURES'
  | 'PERSISTING'
  | 'COMPLETED'
  | 'FAILED';

export type DocumentType =
  | 'PURCHASE_NOTICE'
  | 'PURCHASE_CONFIRMATION'
  | 'NOT_RELEVANT';
