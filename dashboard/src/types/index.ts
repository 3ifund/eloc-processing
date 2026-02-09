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
  ner_validated_count?: number;  // Fields validated by NER
  ner_applicable_count?: number;  // Fields where NER applies
  llm_only_count?: number;  // Fields using LLM agreement only
}

export interface SignatureVerificationResult {
  company_signed: boolean;
  investor_signed: boolean;
  both_signed: boolean;
  company_signatory?: string;
  investor_signatory?: string;
  notes?: string;
  llm_agreement?: boolean;  // Whether Claude and OpenAI agreed
  agreement_details?: {
    fields_agreed?: number;
    total_fields?: number;
    agreement_rate?: number;
    all_agree?: boolean;
    claude_error?: string;
    openai_error?: string;
  };
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
  not_relevant_reason?: string;  // Reason for skipping (e.g., countersigned Purchase Notice)
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
  // Signature verification stats (for Purchase Confirmations)
  signature_verification_counts?: Record<string, number>;  // both_signed, investor_only, company_only, neither
  signature_llm_agreement_counts?: Record<string, number>;  // agree, disagree
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

// Extracted field with value and confidence
export interface ExtractedFieldValue {
  value: string | number | boolean | null;
  confidence: number;
}

// Nested extracted fields object (matches MongoDB structure)
export interface ExtractedFields {
  company_symbol?: ExtractedFieldValue;
  company_name?: ExtractedFieldValue;
  agreement_date?: ExtractedFieldValue;
  company_signator?: ExtractedFieldValue;
  signatory_title?: ExtractedFieldValue;
  purchase_notice_company_signature?: ExtractedFieldValue;
  vwap_purchase_share_amount?: ExtractedFieldValue;
  vwap_purchase_exercise_date?: ExtractedFieldValue;
  vwap_purchase_period_start_date?: ExtractedFieldValue;
  vwap_purchase_period_end_date?: ExtractedFieldValue;
  vwap_purchase_settlement_date?: ExtractedFieldValue;
  aggregate_limit_available?: ExtractedFieldValue;
  sender_name?: ExtractedFieldValue;
  email_subject?: ExtractedFieldValue;
  [key: string]: ExtractedFieldValue | undefined;  // Allow dynamic field access
}

// Confirmation signature verification result
export interface ConfirmationSignatureVerification {
  purchase_confirmation_investor_signature?: boolean;
  purchase_confirmation_company_signature?: boolean;
  investor_signatory?: string;
  company_signatory?: string;
  investor_company?: string;
  target_company?: string;
  vwap_purchase_share_amount?: number;
  vwap_purchase_exercise_date?: string;
  verification_notes?: string;
  both_parties_signed?: boolean;
  llm_agreement?: boolean;
  agreement_details?: {
    fields_agreed?: number;
    total_fields?: number;
    agreement_rate?: number;
  };
}

// Full ELOC data from eloc_data MongoDB collection
export interface ElocData {
  eloc_id: string;
  received_at?: string;
  purchase_notice_market_data_date?: string;
  purchase_notice_filename?: string;
  attachment_hash?: string;
  created_at?: string;
  modified_at?: string;
  source?: string;
  // Extracted fields are nested under extracted_fields in MongoDB
  extracted_fields?: ExtractedFields;
  // Confirmation info
  has_confirmation?: boolean;
  countersigned_purchase_confirmation_filename?: string;
  countersigned_purchase_confirmation_received_at?: string;
  countersigned_purchase_confirmation_signature_verification?: ConfirmationSignatureVerification;
}
