import type { ChatResult } from "@/shared/api/types";
import { MarkdownContent } from "@/shared/components/ui/markdown-content";
import { parseThinkBlocks } from "@/shared/libs/utils";
import { ThinkBlock } from "./ThinkBlock";

export function AgentBubble({ result }: { result: ChatResult }) {
  const showBadge = result.status && result.status !== "answered";
  const { thinkBlocks, answer } = parseThinkBlocks(result.answer ?? "");

  return (
    <div className="flex justify-start">
      <div className="max-w-[80%] space-y-2">
        {showBadge && (
          <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium border bg-gray-100 text-gray-600 border-gray-200">
            {result.status}
          </span>
        )}
        {thinkBlocks.length > 0 && <ThinkBlock blocks={thinkBlocks} />}
        <div className="px-3 py-2 rounded-xl rounded-bl-sm bg-gray-100 text-gray-800 text-sm">
          {answer ? (
            <MarkdownContent content={answer} />
          ) : (
            <span className="text-gray-400 text-xs">(no answer)</span>
          )}
        </div>
        {Array.isArray(result.context_terms) &&
          (result.context_terms as string[]).length > 0 && (
            <div className="flex flex-wrap gap-1">
              {(result.context_terms as string[]).map((term) => (
                <span
                  key={term}
                  className="px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 text-xs"
                >
                  {term}
                </span>
              ))}
            </div>
          )}
      </div>
    </div>
  );
}
