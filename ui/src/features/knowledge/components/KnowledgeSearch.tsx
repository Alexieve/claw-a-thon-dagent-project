import { BookOpen, Loader2, Search } from "lucide-react";
import { useState } from "react";
import { useSearchKnowledge } from "@/shared/api/hooks";
import { useDebounce } from "@/shared/hooks/use-debounce";
import { EmptyState } from "@/shared/components/ui/empty-state";
import { ErrorMessage } from "@/shared/components/ui/error-message";
import { KnowledgeCard } from "./KnowledgeCard";

export function KnowledgeSearch() {
  const [query, setQuery] = useState("");
  const debouncedQuery = useDebounce(query, 300);
  const { data, isLoading, isError, error } = useSearchKnowledge(debouncedQuery);
  const items = data?.knowledge ?? [];

  return (
    <div className="space-y-4">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search knowledge base..."
          className="w-full pl-9 pr-4 py-2.5 border border-gray-300 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent bg-white shadow-sm"
        />
        {isLoading && (
          <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 animate-spin" />
        )}
      </div>

      <ErrorMessage error={isError ? (error as Error) : null} />

      {!isLoading && !isError && items.length === 0 && (
        <EmptyState
          icon={BookOpen}
          title={query ? "No results found" : "No knowledge yet"}
          description={
            query
              ? `No approved knowledge matches "${query}"`
              : "Teach the agent and approve candidates to build the knowledge base."
          }
        />
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {items.map((item) => (
          <KnowledgeCard key={item.id} item={item} />
        ))}
      </div>
    </div>
  );
}
