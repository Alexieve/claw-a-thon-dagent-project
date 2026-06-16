import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { post } from "./client";
import type {
  AnalyzeTextResult,
  AppendTeachMessagePayload,
  AppendTeachMessageResult,
  CandidateStatus,
  ChatPayload,
  ChatResult,
  ChatSessionListResult,
  ConfirmTeachSessionPayload,
  ConfirmTeachSessionResult,
  GetChatHistoryResult,
  IngestDocumentPayload,
  IngestDocumentResult,
  ListCandidatesResult,
  ReviewCandidatePayload,
  ReviewCandidateResult,
  SearchKnowledgeResult,
  StartTeachSessionPayload,
  StartTeachSessionResult,
  StorageStatusResult,
  SummarizeTeachSessionPayload,
  SummarizeTeachSessionResult,
  TeachTextPayload,
  TeachTextResult,
} from "./types";

export const queryKeys = {
  candidates: (status: CandidateStatus | "") => ["candidates", status] as const,
  knowledge: (query: string) => ["knowledge", query] as const,
  storageStatus: () => ["storage_status"] as const,
};

export function useListCandidates(status: CandidateStatus | "") {
  return useQuery({
    queryKey: queryKeys.candidates(status),
    queryFn: () =>
      post<ListCandidatesResult>({ action: "list_candidates", status }),
    staleTime: 15_000,
  });
}

export function useSearchKnowledge(query: string) {
  return useQuery({
    queryKey: queryKeys.knowledge(query),
    queryFn: () =>
      post<SearchKnowledgeResult>({ action: "search_knowledge", query }),
    enabled: true,
    staleTime: 30_000,
  });
}

export function useTeachText() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: TeachTextPayload) =>
      post<TeachTextResult>({ action: "teach_text", ...payload }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["candidates"] });
    },
  });
}

export function useReviewCandidate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ReviewCandidatePayload) =>
      post<ReviewCandidateResult>({ action: "review_candidate", ...payload }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["candidates"] });
      qc.invalidateQueries({ queryKey: ["knowledge"] });
    },
  });
}

export function useAnalyzeText() {
  return useMutation({
    mutationFn: (text: string) =>
      post<AnalyzeTextResult>({ action: "analyze_text", text }),
  });
}

export function useIngestDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: IngestDocumentPayload) =>
      post<IngestDocumentResult>({ action: "ingest_document", ...payload }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["candidates"] });
    },
  });
}

export function useStartTeachSession() {
  return useMutation({
    mutationFn: (payload: StartTeachSessionPayload) =>
      post<StartTeachSessionResult>({ action: "start_teach_session", ...payload }),
  });
}

export function useAppendTeachMessage() {
  return useMutation({
    mutationFn: (payload: AppendTeachMessagePayload) =>
      post<AppendTeachMessageResult>({ action: "append_teach_message", ...payload }),
  });
}

export function useSummarizeTeachSession() {
  return useMutation({
    mutationFn: (payload: SummarizeTeachSessionPayload) =>
      post<SummarizeTeachSessionResult>({ action: "summarize_teach_session", ...payload }),
  });
}

export function useConfirmTeachSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ConfirmTeachSessionPayload) =>
      post<ConfirmTeachSessionResult>({ action: "confirm_teach_session", ...payload }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["candidates"] });
      qc.invalidateQueries({ queryKey: ["knowledge"] });
    },
  });
}

export function useStorageStatus() {
  return useQuery({
    queryKey: queryKeys.storageStatus(),
    queryFn: () => post<StorageStatusResult>({ action: "storage_status" }),
    staleTime: 60_000,
  });
}

export function useChat() {
  return useMutation({
    mutationFn: (payload: ChatPayload) =>
      post<ChatResult>({ action: "chat", ...payload }),
  });
}

export function useListChatSessions() {
  return useQuery({
    queryKey: ["chat_sessions"],
    queryFn: () => post<ChatSessionListResult>({ action: "list_chat_sessions" }),
  });
}

export function useGetChatHistory(sessionId: string | null) {
  return useQuery({
    queryKey: ["chat_history", sessionId],
    queryFn: () =>
      post<GetChatHistoryResult>({ action: "get_chat_history", session_id: sessionId }),
    enabled: !!sessionId,
    staleTime: Infinity,
  });
}
