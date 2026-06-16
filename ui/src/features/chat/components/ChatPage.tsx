import { useQueryClient } from "@tanstack/react-query";
import { Loader2, MessageSquare, Send } from "lucide-react";
import { ChatHistorySkeleton } from "./ChatHistorySkeleton";
import { useEffect, useRef, useState } from "react";
import { useChat, useGetChatHistory } from "@/shared/api/hooks";
import type { ChatResult } from "@/shared/api/types";
import { ErrorMessage } from "@/shared/components/ui/error-message";
import { MarkdownContent } from "@/shared/components/ui/markdown-content";
import { useChatStore } from "@/store/chat.store";
import { AgentBubble } from "./AgentBubble";

type ChatMessage =
  | { role: "user"; text: string; id: string }
  | { role: "agent"; result: ChatResult; id: string };

export function ChatPage() {
  const { activeSessionId, setActiveSession } = useChatStore();
  const queryClient = useQueryClient();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [chatSessionId, setChatSessionId] = useState(activeSessionId ?? "");
  const mutation = useChat();
  const { data: historyData, isLoading: isLoadingHistory } =
    useGetChatHistory(activeSessionId);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  useEffect(() => {
    if (activeSessionId === null) {
      setMessages([]);
      setChatSessionId("");
    } else {
      setChatSessionId(activeSessionId);
    }
  }, [activeSessionId]);

  useEffect(() => {
    if (!activeSessionId || !historyData) return;

    const loaded: ChatMessage[] = historyData.messages.map((m) => {
      if (m.role === "user") {
        return { role: "user", text: m.content, id: crypto.randomUUID() };
      }
      return {
        role: "agent",
        result: {
          answer: m.content,
          status: "answered",
          context_terms: [],
          requires_confirmation: false,
          intent: "",
          question: "",
          chat_session_id: activeSessionId,
          pending_action_id: "",
          pending_action_type: "",
          confirm_options: [],
          session_state: "",
          missing: [],
          conversation_context_used: false,
          context_backend: "",
          used_knowledge_ids: [],
          used_dictionary_ids: [],
          used_example_ids: [],
          debug: {},
          pending_action: { id: "", type: "", status: "", confirm_options: [] },
        } as ChatResult,
        id: crypto.randomUUID(),
      };
    });

    setMessages(loaded);
  }, [activeSessionId, historyData]);

  const lastAgentResult =
    messages.length > 0 && messages[messages.length - 1].role === "agent"
      ? (
          messages[messages.length - 1] as {
            role: "agent";
            result: ChatResult;
            id: string;
          }
        ).result
      : null;

  const pendingAction =
    lastAgentResult?.requires_confirmation && lastAgentResult.pending_action.id
      ? lastAgentResult.pending_action
      : null;

  const handleSend = () => {
    const msg = input.trim();
    if (!msg || mutation.isPending) return;

    setMessages((prev) => [
      ...prev,
      { role: "user", text: msg, id: crypto.randomUUID() },
    ]);
    setInput("");

    mutation.mutate(
      { message: msg, session_id: chatSessionId || undefined },
      {
        onSuccess: (result) => {
          if (result.chat_session_id) {
            setChatSessionId(result.chat_session_id);
            setActiveSession(result.chat_session_id);
            queryClient.invalidateQueries({ queryKey: ["chat_sessions"] });
            queryClient.invalidateQueries({
              queryKey: ["chat_history", result.chat_session_id],
            });
          }
          setMessages((prev) => [
            ...prev,
            { role: "agent", result, id: crypto.randomUUID() },
          ]);
        },
      },
    );
  };

  const handleConfirm = (choice: string) => {
    if (!pendingAction || mutation.isPending) return;

    setMessages((prev) => [
      ...prev,
      { role: "user", text: choice, id: crypto.randomUUID() },
    ]);

    mutation.mutate(
      {
        message: choice,
        session_id: chatSessionId || undefined,
        pending_action_id: pendingAction.id,
      },
      {
        onSuccess: (result) => {
          if (result.chat_session_id) {
            setChatSessionId(result.chat_session_id);
            setActiveSession(result.chat_session_id);
            queryClient.invalidateQueries({ queryKey: ["chat_sessions"] });
            queryClient.invalidateQueries({
              queryKey: ["chat_history", result.chat_session_id],
            });
          }
          setMessages((prev) => [
            ...prev,
            { role: "agent", result, id: crypto.randomUUID() },
          ]);
        },
      },
    );
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col h-full -m-6">
      <div className="px-6 py-4 border-b border-gray-200 bg-white shrink-0">
        <h1 className="text-2xl font-bold text-gray-900">Chat</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Ask anything about your business metrics and knowledge
        </p>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
        {messages.length === 0 && isLoadingHistory && <ChatHistorySkeleton />}
        {messages.length === 0 && !isLoadingHistory && (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-gray-400">
            <MessageSquare className="w-10 h-10 opacity-30" />
            <p className="text-sm">
              Ask anything — metrics, terms, data questions
            </p>
          </div>
        )}

        {messages.map((msg) =>
          msg.role === "user" ? (
            <div key={msg.id} className="flex justify-end">
              <div className="max-w-[80%] px-3 py-2 rounded-xl rounded-br-sm bg-indigo-600 text-white text-sm">
                <MarkdownContent
                  content={msg.text}
                  className="prose-invert prose-a:text-indigo-200"
                />
              </div>
            </div>
          ) : (
            <AgentBubble key={msg.id} result={msg.result} />
          ),
        )}

        {mutation.isPending && (
          <div className="flex justify-start">
            <div className="px-3 py-2 rounded-xl rounded-bl-sm bg-gray-100 text-gray-400 text-sm flex items-center gap-2">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              Thinking…
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      <div className="border-t border-gray-200 px-4 py-3 bg-white shrink-0">
        <ErrorMessage error={mutation.error} />

        {pendingAction ? (
          <div className="flex flex-wrap gap-2 mt-1">
            {pendingAction.confirm_options.map((opt) => (
              <button
                key={opt}
                onClick={() => handleConfirm(opt)}
                disabled={mutation.isPending}
                className="px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-60 bg-indigo-600 text-white hover:bg-indigo-700"
              >
                {opt}
              </button>
            ))}
          </div>
        ) : (
          <form
            className="flex gap-2 mt-1"
            onSubmit={(e) => {
              e.preventDefault();
              handleSend();
            }}
          >
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={2}
              disabled={mutation.isPending}
              placeholder="Ask a question… (Enter to send, Shift+Enter for newline)"
              className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm resize-none focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent disabled:opacity-60"
            />
            <button
              type="submit"
              disabled={mutation.isPending || !input.trim()}
              className="self-end px-3 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-60 transition-colors"
            >
              {mutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Send className="w-4 h-4" />
              )}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
