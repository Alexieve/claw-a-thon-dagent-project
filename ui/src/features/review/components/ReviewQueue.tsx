import { useState } from "react";
import { Loader2 } from "lucide-react";
import { useListCandidates } from "@/shared/api/hooks";
import type { CandidateStatus } from "@/shared/api/types";
import { EmptyState } from "@/shared/components/ui/empty-state";
import { CandidateCard } from "./CandidateCard";

const FILTERS: { label: string; value: CandidateStatus | "" }[] = [
  { label: "All", value: "" },
  { label: "Pending", value: "pending_review" },
  { label: "Pending Changes", value: "pending_change" },
  { label: "Approved", value: "approved" },
  { label: "Rejected", value: "rejected" },
  { label: "Conflict", value: "conflict" },
];

export function ReviewQueue() {
  const [activeFilter, setActiveFilter] = useState<CandidateStatus | "">("");
  const { data, isLoading, isError } = useListCandidates(activeFilter);
  const candidates = data?.candidates ?? [];

  return (
    <div className="space-y-4">
      <div className="flex gap-1 flex-wrap">
        {FILTERS.map(({ label, value }) => (
          <button
            key={value}
            onClick={() => setActiveFilter(value)}
            className={
              activeFilter === value
                ? "px-3 py-1.5 rounded-lg text-sm font-medium bg-indigo-600 text-white"
                : "px-3 py-1.5 rounded-lg text-sm font-medium bg-gray-100 text-gray-600 hover:bg-gray-200 transition-colors"
            }
          >
            {label}
          </button>
        ))}
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-gray-400 py-8 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading candidates...
        </div>
      )}

      {isError && (
        <div className="px-4 py-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
          Failed to load candidates. Is the API running?
        </div>
      )}

      {!isLoading && !isError && candidates.length === 0 && (
        <EmptyState title="No candidates" description="No candidates match this filter." />
      )}

      <div className="space-y-3">
        {candidates.map((c) => (
          <CandidateCard key={c.id} candidate={c} />
        ))}
      </div>
    </div>
  );
}
