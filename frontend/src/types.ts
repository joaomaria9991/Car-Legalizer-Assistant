export type DavValue = string | number | boolean | null;

export type DavFieldMeta = {
  origin: "extracted" | "induced" | "user" | "missing" | "conflict" | "not_applicable";
  status?: "filled" | "missing" | "needs_review" | "conflict" | "not_applicable";
  reason?: string;
  source?: string;
  source_doc?: string;
  source_page?: string;
  confidence?: number;
  value?: unknown;
  alternatives?: Array<Record<string, unknown>>;
};

export type UiFieldPrompt = {
  field?: string;
  label?: string;
  explain?: string;
  where?: string;
  examples?: string[];
};

export type DavDecisionOption = {
  label: string;
  value?: unknown;
  description?: string;
  field_updates?: Array<Record<string, unknown>>;
};

export type DavDecision = {
  id: string;
  kind: "applicability" | "missing" | string;
  field: string;
  label: string;
  message: string;
  reason?: string;
  impact?: string;
  options: DavDecisionOption[];
};

export type UiOut = {
  type?: "dav_question" | "dav_ready" | "request_upload" | "info" | "error" | string;
  message?: string;
  fields?: Array<string | UiFieldPrompt>;
  decisions?: DavDecision[];
  assistant_message?: string;
  applied?: Array<Record<string, unknown>>;
};

export type AgentProgressEntry = {
  id: string;
  stage:
    | "upload"
    | "classify"
    | "extract"
    | "harmonize"
    | "autofill"
    | "dav_chat"
    | "complete"
    | "error"
    | string;
  status: "queued" | "running" | "done" | "warning" | "error" | string;
  message: string;
  ts: string;
  detail?: Record<string, unknown>;
};

export type ExtractJob = {
  status?: "queued" | "running" | "stale" | "done" | "warning" | "error" | string;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  stale?: boolean;
  last_progress_at?: string | null;
  pages_total?: number;
  pages_done?: number;
};

export type ProcessState = {
  process_id: string;
  fase_atual: string;
  sub_fase?: string | null;
  dados_carro: Record<string, DavValue>;
  dados_fiscal?: Record<string, unknown>;
  docs: Record<string, Record<string, unknown>>;
  flags: {
    ui_out?: UiOut;
    dav_field_meta?: Record<string, DavFieldMeta>;
    agent_progress?: AgentProgressEntry[];
    extract_job?: ExtractJob;
    raw_page_insights?: unknown[];
    [key: string]: unknown;
  };
  prazos?: Record<string, unknown>;
  historico?: string[];
};

export type ProcessSummary = {
  process_id: string;
  fase_atual: string;
  sub_fase?: string | null;
  last_modified?: string | null;
  docs_count: number;
  filled_fields: number;
  total_fields: number;
  missing_fields: number;
  conflict_fields: number;
  not_applicable_fields?: number;
  display_name?: string;
};

export type ProcessListResponse = {
  processes: ProcessSummary[];
};

export type ProcessResponse = {
  success: boolean;
  fase_atual: string;
  sub_fase?: string | null;
  state: ProcessState;
};

export type DocumentPage = {
  page_number: number;
  blob_path: string;
  filename: string;
};

export type ProcessDocument = {
  doc_id: string;
  filename: string;
  category: string;
  status: string;
  confidence?: number | null;
  pages: DocumentPage[];
};

export type ProcessDocumentsResponse = {
  process_id: string;
  documents: ProcessDocument[];
};

export type UploadPage = {
  filename: string;
  blob: Blob;
  sourceName: string;
  pageNumber: number;
};

export type UploadProgress = {
  id: string;
  filename: string;
  sourceName: string;
  status: "queued" | "splitting" | "uploading" | "done" | "error";
  message?: string;
};
