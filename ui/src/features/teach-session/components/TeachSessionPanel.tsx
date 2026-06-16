import { Link } from "@tanstack/react-router";
import { ArrowRight, CheckCircle2, Loader2, MessageCircle, Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  useAppendTeachMessage,
  useConfirmTeachSession,
  useStartTeachSession,
  useSummarizeTeachSession,
} from "@/shared/api/hooks";
import type {
  ConfirmTeachSessionResult,
  Knowledge,
  StartTeachSessionResult,
  TeachSession,
} from "@/shared/api/types";
import { KindBadge } from "@/shared/components/ui/badge";
import { ErrorMessage } from "@/shared/components/ui/error-message";

type ConversationEntry =
  | { role: "user"; content: string }
  | { role: "agent"; content: string; result?: StartTeachSessionResult };

type PanelState =
  | { phase: "idle" }
  | { phase: "active"; session: TeachSession; lastResult: StartTeachSessionResult }
  | { phase: "done"; result: ConfirmTeachSessionResult };

export function TeachSessionPanel() {
  const [state, setState] = useState<PanelState>({ phase: "idle" });
  const [message, setMessage] = useState("");
  const [stakeholder, setStakeholder] = useState("");
  const [team, setTeam] = useState("");
  const [reply, setReply] = useState("");
  const [conversationLog, setConversationLog] = useState<ConversationEntry[]>([]);
  const replyRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const startMutation = useStartTeachSession();
  const appendMutation = useAppendTeachMessage();
  const summarizeMutation = useSummarizeTeachSession();
  const confirmMutation = useConfirmTeachSession();

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [conversationLog.length]);

  const handleStart = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmedMessage = message.trim();
    if (!trimmedMessage) return;
    startMutation.mutate(
      { message: trimmedMessage, stakeholder: stakeholder || undefined, team: team || undefined },
      {
        onSuccess: (result) => {
          setState({ phase: "active", session: result.session, lastResult: result });
          const agentContent = result.question ?? result.confirmation_prompt ?? "";
          setConversationLog([
            { role: "user", content: trimmedMessage },
            ...(agentContent ? [{ role: "agent" as const, content: agentContent, result }] : []),
          ]);
          setMessage("");
          setStakeholder("");
          setTeam("");
        },
      }
    );
  };

  const handleReply = (e: React.FormEvent) => {
    e.preventDefault();
    if (state.phase !== "active") return;
    const trimmedReply = reply.trim();
    if (!trimmedReply) return;
    appendMutation.mutate(
      { session_id: state.session.id, message: trimmedReply },
      {
        onSuccess: (result) => {
          setState({ phase: "active", session: result.session, lastResult: result });
          const agentContent = result.question ?? result.confirmation_prompt ?? "";
          setConversationLog((prev) => [
            ...prev,
            { role: "user", content: trimmedReply },
            ...(agentContent ? [{ role: "agent" as const, content: agentContent, result }] : []),
          ]);
          setReply("");
        },
      }
    );
  };

  const handleSummarize = () => {
    if (state.phase !== "active") return;
    summarizeMutation.mutate(
      { session_id: state.session.id },
      {
        onSuccess: (result) => {
          setState({ phase: "active", session: result.session, lastResult: result });
          const agentContent = result.confirmation_prompt ?? "Ready to confirm.";
          setConversationLog((prev) => [
            ...prev,
            { role: "agent", content: agentContent, result },
          ]);
        },
      }
    );
  };

  const handleConfirm = (decision: "confirm" | "cancel") => {
    if (state.phase !== "active") return;
    confirmMutation.mutate(
      { session_id: state.session.id, decision },
      {
        onSuccess: (result) => {
          setState({ phase: "done", result });
        },
      }
    );
  };

  const handleReset = () => {
    setState({ phase: "idle" });
    setConversationLog([]);
    startMutation.reset();
    appendMutation.reset();
    summarizeMutation.reset();
    confirmMutation.reset();
  };

  if (state.phase === "done") {
    return <DoneView result={state.result} onReset={handleReset} />;
  }

  if (state.phase === "idle") {
    return (
      <form onSubmit={handleStart} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Describe the knowledge
          </label>
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            rows={4}
            placeholder="E.g. 'FPU là user có first payment. Đây là metric quan trọng của team Growth.'"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm resize-y focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Stakeholder
            </label>
            <input
              type="text"
              value={stakeholder}
              onChange={(e) => setStakeholder(e.target.value)}
              placeholder="e.g. Linh"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Team
            </label>
            <input
              type="text"
              value={team}
              onChange={(e) => setTeam(e.target.value)}
              placeholder="e.g. Growth"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
          </div>
        </div>

        <ErrorMessage error={startMutation.error} />

        <button
          type="submit"
          disabled={startMutation.isPending || !message.trim()}
          className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-60 transition-colors"
        >
          {startMutation.isPending ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <MessageCircle className="w-4 h-4" />
          )}
          {startMutation.isPending ? "Starting session..." : "Start Session"}
        </button>
      </form>
    );
  }

  // active phase
  const { session } = state;
  const isBusy = appendMutation.isPending || summarizeMutation.isPending || confirmMutation.isPending;
  const isAwaiting = session.status === "awaiting_confirmation";

  // Find the index of the last agent entry that has a draft with visible fields
  const lastDraftIndex = conversationLog.reduce<number>((acc, entry, i) => {
    if (entry.role === "agent" && entry.result?.draft && hasDraftFields(entry.result.draft)) {
      return i;
    }
    return acc;
  }, -1);

  return (
    <div className="space-y-4">
      {/* Conversation log */}
      <div className="space-y-3 max-h-[480px] overflow-y-auto pr-1">
        {conversationLog.map((entry, i) => (
          <div key={i} className="space-y-1.5">
            <div className={entry.role === "user" ? "flex justify-end" : "flex justify-start"}>
              <div
                className={
                  entry.role === "user"
                    ? "max-w-[80%] px-3 py-2 rounded-xl rounded-br-sm bg-indigo-600 text-white text-sm"
                    : "max-w-[80%] px-3 py-2 rounded-xl rounded-bl-sm bg-gray-100 text-gray-800 text-sm"
                }
              >
                {entry.content}
              </div>
            </div>

            {/* Inline draft card for agent messages that have definition fields */}
            {entry.role === "agent" &&
              entry.result?.draft &&
              hasDraftFields(entry.result.draft) && (
                <div className="flex justify-start">
                  <div className="max-w-[90%] w-full">
                    <DraftSummaryCard
                      lastResult={entry.result}
                      onConfirm={i === lastDraftIndex ? () => handleConfirm("confirm") : undefined}
                      confirmDisabled={!isAwaiting || isBusy}
                      confirmPending={confirmMutation.isPending}
                    />
                  </div>
                </div>
              )}
          </div>
        ))}

        {(appendMutation.isPending || summarizeMutation.isPending) && (
          <div className="flex justify-start">
            <div className="px-3 py-2 rounded-xl rounded-bl-sm bg-gray-100 text-gray-400 text-sm flex items-center gap-2">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              Thinking…
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Unified chat input */}
      <div className="space-y-2">
        <form onSubmit={handleReply} className="flex gap-2">
          <textarea
            ref={replyRef}
            value={reply}
            onChange={(e) => setReply(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (reply.trim()) handleReply(e as unknown as React.FormEvent);
              }
            }}
            rows={2}
            placeholder="Reply to the agent… (Enter to send, Shift+Enter for newline)"
            disabled={isBusy}
            className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm resize-none focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent disabled:bg-gray-50"
          />
          <button
            type="submit"
            disabled={isBusy || !reply.trim()}
            className="self-end px-3 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-60 transition-colors"
          >
            {appendMutation.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </button>
        </form>

        {/* Session action buttons */}
        <div className="flex gap-2">
          <button
            onClick={handleSummarize}
            disabled={isBusy}
            className="flex items-center gap-1.5 px-3 py-1.5 border border-indigo-300 text-indigo-600 rounded-lg text-xs font-medium hover:bg-indigo-50 disabled:opacity-50 transition-colors"
          >
            {summarizeMutation.isPending ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : null}
            {summarizeMutation.isPending ? "Summarizing…" : "Summarize"}
          </button>
          <button
            onClick={() => handleConfirm("cancel")}
            disabled={isBusy}
            className="px-3 py-1.5 border border-red-200 text-red-500 rounded-lg text-xs font-medium hover:bg-red-50 disabled:opacity-50 transition-colors"
          >
            {confirmMutation.isPending ? "Cancelling…" : "Cancel session"}
          </button>
        </div>

        <ErrorMessage error={appendMutation.error ?? summarizeMutation.error ?? confirmMutation.error} />
      </div>
    </div>
  );
}

const DISPLAY_FIELDS = [
  { key: "name", label: "Name" },
  { key: "definition", label: "Definition" },
  { key: "domain", label: "Domain" },
  { key: "owner", label: "Owner" },
  { key: "kind", label: "Kind" },
  { key: "formula", label: "Formula" },
] as const;

function hasDraftFields(draft: Record<string, unknown>): boolean {
  return DISPLAY_FIELDS.some(({ key }) => {
    const v = draft[key];
    return v !== undefined && v !== null && v !== "";
  });
}

function DraftSummaryCard({
  lastResult,
  onConfirm,
  confirmDisabled,
  confirmPending,
}: {
  lastResult: StartTeachSessionResult;
  onConfirm?: () => void;
  confirmDisabled?: boolean;
  confirmPending?: boolean;
}) {
  const { draft, confirmation_prompt } = lastResult;

  const visibleFields = draft
    ? DISPLAY_FIELDS.filter(({ key }) => {
        const v = draft[key];
        return v !== undefined && v !== null && v !== "";
      })
    : [];

  return (
    <div className="rounded-lg border border-indigo-200 bg-white overflow-hidden text-sm">
      {confirmation_prompt && (
        <div className="px-4 py-2.5 bg-indigo-50 text-indigo-800 border-b border-indigo-200">
          {confirmation_prompt}
        </div>
      )}
      {visibleFields.length > 0 && (
        <div className="border-l-4 border-indigo-500 px-4 py-3 space-y-1.5">
          {visibleFields.map(({ key, label }) => (
            <div key={key} className="flex gap-2">
              <span className="w-24 shrink-0 text-xs font-medium text-gray-500 uppercase tracking-wide pt-0.5">
                {label}
              </span>
              <span className="text-gray-800 break-words">{String(draft![key])}</span>
            </div>
          ))}
        </div>
      )}
      {onConfirm && (
        <div className="px-4 py-2.5 border-t border-indigo-100 bg-gray-50">
          <button
            onClick={onConfirm}
            disabled={confirmDisabled}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 text-white rounded-lg text-xs font-medium hover:bg-green-700 disabled:opacity-50 transition-colors"
          >
            {confirmPending ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <CheckCircle2 className="w-3 h-3" />
            )}
            {confirmPending ? "Confirming…" : "Confirm this definition"}
          </button>
          {confirmDisabled && !confirmPending && (
            <p className="mt-1 text-xs text-gray-400">Click Summarize first to enable confirmation.</p>
          )}
        </div>
      )}
    </div>
  );
}

function DoneView({
  result,
  onReset,
}: {
  result: ConfirmTeachSessionResult;
  onReset: () => void;
}) {
  const { knowledge_created, change_requests, session } = result;
  const cancelled = session.status === "cancelled";

  if (cancelled) {
    return (
      <div className="space-y-4">
        <div className="px-4 py-3 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-600">
          Session cancelled.
        </div>
        <button
          onClick={onReset}
          className="text-sm text-indigo-600 hover:text-indigo-800 underline"
        >
          Start a new session
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {knowledge_created.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-green-600" />
            <span className="text-sm font-medium text-gray-700">
              {knowledge_created.length} committed directly
            </span>
          </div>
          {knowledge_created.map((k: Knowledge) => (
            <div key={k.id} className="bg-green-50 border border-green-200 rounded-lg p-3 space-y-1">
              <div className="flex items-center gap-2">
                <span className="font-medium text-gray-800 text-sm">{k.name}</span>
                <KindBadge kind={k.kind} />
              </div>
              <p className="text-xs text-gray-600">{k.canonical_definition}</p>
            </div>
          ))}
        </div>
      )}

      {change_requests.length > 0 && (
        <div className="px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-800">
          {change_requests.length} change request{change_requests.length !== 1 ? "s" : ""} sent for review.{" "}
          <Link to="/review" className="underline font-medium">
            Review queue <ArrowRight className="inline w-3 h-3" />
          </Link>
        </div>
      )}

      <button
        onClick={onReset}
        className="text-sm text-indigo-600 hover:text-indigo-800 underline"
      >
        Start a new session
      </button>
    </div>
  );
}
