export interface ApiResponse<T> {
  status: "success" | "error";
  timestamp: string;
  session_id: string;
  result: T;
  error?: string;
}

export type CandidateKind = "metric" | "term" | "dimension" | "business_rule" | "synonym";
export type CandidateStatus = "pending_review" | "pending_change" | "approved" | "rejected" | "conflict";

export interface Candidate {
  id: string;
  source_event_id: string;
  kind: CandidateKind;
  name: string;
  definition: string;
  paraphrases: string[];
  formula?: string | null;
  conditions: string[];
  domain: string;
  owner: string;
  confidence: number;
  status: CandidateStatus;
  conflict_with?: string;
  created_at: string;
  // pending_change fields
  change_type?: string;
  target_knowledge_id?: string;
  proposed_by?: string;
  original_owner?: string;
  change_summary?: string;
  before?: Record<string, unknown>;
  after?: Record<string, unknown>;
}

export interface Knowledge {
  id: string;
  kind: CandidateKind;
  name: string;
  canonical_definition: string;
  paraphrases: string[];
  formula?: string | null;
  conditions: string[];
  domain: string;
  owner: string;
  status: string;
  evidence_event_ids: string[];
  candidate_ids: string[];
  created_at: string;
  updated_at: string;
  version?: number;
  logic?: string;
  examples?: string[];
  change_history?: unknown[];
}

// teach_text
export interface TeachTextPayload {
  text: string;
  stakeholder?: string;
  team?: string;
  domain?: string;
  owner?: string;
}
export interface TeachTextResult {
  raw_event: unknown;
  knowledge_created: Knowledge[];
  candidates: Candidate[];
  change_requests: Candidate[];
}

// list_candidates
export interface ListCandidatesResult {
  candidates: Candidate[];
}

// review_candidate
export interface ReviewCandidatePayload {
  candidate_id: string;
  decision: "approve" | "reject";
  updates?: Partial<Omit<Candidate, "id" | "source_event_id" | "status" | "created_at">>;
}
export interface ReviewCandidateResult {
  candidate: Candidate;
  knowledge: Knowledge | null;
  answer?: string;
}

// search_knowledge
export interface SearchKnowledgeResult {
  knowledge: Knowledge[];
}

// delete_knowledge (hard delete, no approval)
export interface DeleteKnowledgePayload {
  knowledge_id: string;
}
export interface DeleteKnowledgeResult {
  deleted: boolean;
  knowledge_id: string;
  name: string;
  answer?: string;
}

// analyze_text
export interface AnalyzeTextResult {
  known: Knowledge[];
  pending: Candidate[];
  conflicts: Candidate[];
  unknown: string[];
  detected_terms: string[];
  answer: string;
}

// ingest_document
export interface IngestDocumentPayload {
  text: string;
  title?: string;
  stakeholder?: string;
  team?: string;
  domain?: string;
  owner?: string;
}
export interface IngestDocumentResult {
  document_id: string;
  chunks: unknown[];
  knowledge_created: Knowledge[];
  change_requests: Candidate[];
  candidates: Candidate[];
}

// Teaching Session
export type TeachSessionStatus =
  | "clarifying"
  | "awaiting_confirmation"
  | "committed"
  | "pending_approval"
  | "cancelled";

export interface TeachSessionMessage {
  role: "user" | "agent";
  content: string;
  created_at: string;
}

export interface TeachSession {
  id: string;
  status: TeachSessionStatus;
  messages: TeachSessionMessage[];
  draft?: Record<string, unknown>;
  stakeholder?: string;
  team?: string;
  domain?: string;
  owner?: string;
  created_at: string;
  updated_at: string;
}

export interface StartTeachSessionPayload {
  message: string;
  stakeholder?: string;
  team?: string;
  domain?: string;
  owner?: string;
}
export interface StartTeachSessionResult {
  session: TeachSession;
  session_id: string;
  status: TeachSessionStatus;
  draft?: Record<string, unknown>;
  question?: string;
  summary?: Record<string, unknown>;
  confirmation_prompt?: string;
}

export interface AppendTeachMessagePayload {
  session_id: string;
  message: string;
}
export type AppendTeachMessageResult = StartTeachSessionResult;

export interface SummarizeTeachSessionPayload {
  session_id: string;
}
export type SummarizeTeachSessionResult = StartTeachSessionResult;

export interface ConfirmTeachSessionPayload {
  session_id: string;
  decision: "confirm" | "cancel";
}
export interface ConfirmTeachSessionResult {
  session: TeachSession;
  raw_event?: unknown;
  knowledge_created: Knowledge[];
  change_requests: Candidate[];
  candidates?: Candidate[];
}

// storage_status
export interface StorageStatusResult {
  backend: "json" | "postgres";
  database_configured: boolean;
}

export interface ChatSessionMeta {
  id: string;
  title: string;
  created_at: string;
}

export interface ChatSessionListResult {
  sessions: ChatSessionMeta[];
}

export interface ChatHistoryMessage {
  role: "user" | "assistant";
  content: string;
  created_at?: string;
}

export interface GetChatHistoryResult {
  session_id: string;
  user_id: string;
  state: string;
  message_count: number;
  messages: ChatHistoryMessage[];
  created_at: string;
  updated_at: string;
}

// chat
export interface ChatPayload {
  message: string;
  user_id?: string;
  session_id?: string;
  pending_action_id?: string;
}

export interface ChatPendingAction {
  id: string;
  type: string;
  status: string;
  confirm_options: string[];
}

export interface ChatResult {
  status: string;
  intent: string;
  answer: string;
  question: string;
  chat_session_id: string;
  requires_confirmation: boolean;
  pending_action_id: string;
  pending_action_type: string;
  confirm_options: string[];
  session_state: string;
  missing: unknown[];
  context_terms: string[];
  conversation_context_used: boolean;
  context_backend: string;
  used_knowledge_ids: string[];
  used_dictionary_ids: string[];
  used_example_ids: string[];
  debug: Record<string, unknown>;
  pending_action: ChatPendingAction;
}
