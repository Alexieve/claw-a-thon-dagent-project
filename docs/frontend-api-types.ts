export type AgentAction = "chat" | "search_knowledge" | "storage_status" | string;

export interface AgentApiError {
  code: string;
  message: string;
  details?: unknown;
}

/** Standard response wrapper for every POST /invocations action. */
export interface AgentApiResponse<T> {
  /** "success" means read result; "error" means render error.message. */
  status: "success" | "error";
  /** Backend ISO timestamp. Useful for logs. */
  timestamp: string;
  /** Optional FE/backend correlation id. */
  request_id?: string;
  /** Envelope session id; for chat, prefer result.chat_session_id. */
  session_id: string | null;
  /** Action result payload when status is "success". */
  result?: T;
  /** Standard error object when status is "error". */
  error?: AgentApiError;
}

export interface ChatRequest {
  /** Send "chat"; can be omitted for backward-compatible message-only payloads. */
  action?: "chat";
  /** User text, or "confirm" / "cancel" for pending actions. */
  message: string;
  /** Stable user id for memory/context. */
  user_id?: string;
  /** Stable chat conversation id. */
  session_id?: string;
  /** Required when confirming/cancelling a specific pending action. */
  pending_action_id?: string;
  /** Dev only: include retrieved knowledge/dictionary/examples/debug details. */
  debug_context?: boolean;
  /** Optional per-request runtime skill toggle. Defaults to backend config. */
  use_runtime_skills?: boolean;
  /** Optional FE-generated correlation id. */
  request_id?: string;
}

export type ChatStatus =
  | "answered"
  | "needs_confirmation"
  | "needs_clarification"
  | "needs_dictionary"
  | "needs_knowledge"
  | "sql_draft"
  | "awaiting_confirmation"
  | "committed"
  | "cancelled"
  | "llm_required"
  | string;

export type ChatIntent =
  | "planner_answer"
  | "knowledge_qa"
  | "data_sql"
  | "teach_knowledge"
  | "conversation_recall"
  | "pending_status"
  | "runtime_skill"
  | string;

export interface PendingAction {
  /** Pending action id to send back as pending_action_id on confirm/cancel. */
  id: string;
  /** Action category. FE mainly cares about data_query for chat phase 1. */
  type: "data_query" | "start_teaching" | "append_teaching" | "commit_teaching" | string;
  /** "pending" when active, empty string when no active action. */
  status: "pending" | "";
  /** Valid user commands, currently usually ["confirm", "cancel"]. */
  confirm_options: string[];
}

export interface MissingContext {
  /** Missing category, e.g. clarification, column_mapping, domain_knowledge. */
  type?: string;
  /** Missing concept/slot, e.g. time_range, output_shape, PU. */
  concept?: string;
  /** Human-readable question FE can show in missing-context cards. */
  question?: string;
  /** Optional backend reason. */
  reason?: string;
  [key: string]: unknown;
}

export interface DebugContext {
  llm_used?: boolean;
  fallback_used?: boolean;
  /** Whether final result.answer was produced by answer synthesis LLM. */
  answer_synthesis_used?: boolean;
  /** Fallback reason: llm_error, empty_answer, invalid_locked_state, llm_not_configured. */
  answer_synthesis_fallback_reason?: string;
  /** Per-stage latency in milliseconds: memory, retrieval, skill_select, planner, execute, total. */
  latency_ms?: Record<string, number>;
  conversation_history_used?: boolean;
  conversation_history_turns?: number;
  memory_hydrated?: boolean;
  memory_sync_status?: string;
  memory_timeout?: boolean;
  memory_latency_ms?: number;
  memory_errors?: string[];
  [key: string]: unknown;
}

export interface ChatResult {
  /** Machine-readable state for FE UI decisions. */
  status: ChatStatus;
  /** Backend-classified intent. Useful for analytics/badges. */
  intent: ChatIntent;
  /** User-facing assistant text. Render this, but never parse it for ids/state/SQL. */
  answer: string;
  /** Question currently handled by backend. */
  question: string;
  /** Canonical session id. Persist this and send it in the next ChatRequest.session_id. */
  chat_session_id: string;
  /** True when FE should show confirmation controls. */
  requires_confirmation: boolean;
  /** Pending action id. Send this back when confirming/cancelling. */
  pending_action_id: string;
  /** Pending action type, e.g. data_query. */
  pending_action_type: string;
  /** Normalized pending action object. */
  pending_action: PendingAction;
  /** Valid confirmation commands for the pending action. */
  confirm_options: string[];
  /** High-level session state. */
  session_state: "idle" | "data_query_pending" | "teaching_draft_active" | string;
  /** Resolved question after context/follow-up handling. */
  resolved_question: string;
  /** True when previous chat context was used to understand this turn. */
  conversation_context_used: boolean;
  /** Context terms inferred from history, e.g. ["PU"]. */
  context_terms: string[];
  /** Context backend source. */
  context_backend: "local" | "agentbase" | "auto" | string;
  /** Missing info/clarification slots. Render cards/forms from this. */
  missing: MissingContext[];
  /** Source ids used by backend. Optional source panel/debug. */
  used_knowledge_ids: string[];
  /** Data dictionary ids used by backend. Optional source panel/debug. */
  used_dictionary_ids: string[];
  /** Approved question example ids used by backend. Optional source panel/debug. */
  used_example_ids: string[];
  /** SQL draft. Show only when status === "sql_draft" and sql is non-empty. */
  sql?: string | null;
  /** Optional SQL/result explanation. */
  explanation?: string | string[];
  /** Dev diagnostics only. Do not render by default. */
  debug?: DebugContext;
  /** Allows backend to add source arrays when debug_context=true. */
  [key: string]: unknown;
}

export interface KnowledgeRecord {
  id: string;
  name: string;
  canonical_definition?: string;
  definition?: string;
  paraphrases?: string[];
  formula?: string;
  domain?: string;
  owner?: string;
  status?: string;
  version?: number;
  [key: string]: unknown;
}

export interface SearchKnowledgeRequest {
  action: "search_knowledge";
  query: string;
  request_id?: string;
}

export interface SearchKnowledgeResult {
  knowledge: KnowledgeRecord[];
}

export interface StorageStatusRequest {
  action: "storage_status";
  request_id?: string;
}

export interface StorageStatusResult {
  /** Supabase/Postgres appears as "postgres". */
  backend: "json" | "postgres" | string;
  database_configured: boolean;
  chat_context_backend: "local" | "agentbase" | "auto" | string;
  chat_context_memory_configured: boolean;
  chat_context_event_limit: number;
  chat_context_fallback_on_memory_error: boolean;
}

export type AgentRequest = ChatRequest | SearchKnowledgeRequest | StorageStatusRequest;

export async function invokeAgent<T>(
  baseUrl: string,
  payload: AgentRequest | Record<string, unknown>,
  fetchImpl: typeof fetch = fetch,
): Promise<AgentApiResponse<T>> {
  const response = await fetchImpl(`${baseUrl}/invocations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  return response.json() as Promise<AgentApiResponse<T>>;
}

export function shouldShowConfirmation(result: ChatResult): boolean {
  return result.requires_confirmation === true && result.pending_action_id !== "";
}

export function shouldShowMissingContext(result: ChatResult): boolean {
  return Array.isArray(result.missing) && result.missing.length > 0;
}

export function shouldShowSqlPreview(result: ChatResult): boolean {
  return result.status === "sql_draft" && Boolean(result.sql);
}

export function buildConfirmRequest(result: ChatResult, userId?: string): ChatRequest {
  return {
    action: "chat",
    message: "confirm",
    user_id: userId,
    session_id: result.chat_session_id,
    pending_action_id: result.pending_action_id,
  };
}

export function buildCancelRequest(result: ChatResult, userId?: string): ChatRequest {
  return {
    action: "chat",
    message: "cancel",
    user_id: userId,
    session_id: result.chat_session_id,
    pending_action_id: result.pending_action_id,
  };
}
