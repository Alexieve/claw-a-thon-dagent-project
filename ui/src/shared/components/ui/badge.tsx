import { cn } from "@/shared/libs/utils";
import type { CandidateStatus } from "@/shared/api/types";

const statusStyles: Record<CandidateStatus, string> = {
  pending_review: "bg-yellow-100 text-yellow-800 border-yellow-200",
  pending_change: "bg-amber-100 text-amber-800 border-amber-200",
  approved: "bg-green-100 text-green-800 border-green-200",
  rejected: "bg-red-100 text-red-800 border-red-200",
  conflict: "bg-orange-100 text-orange-800 border-orange-200",
};

const kindStyles: Record<string, string> = {
  metric: "bg-blue-100 text-blue-800 border-blue-200",
  term: "bg-purple-100 text-purple-800 border-purple-200",
  dimension: "bg-indigo-100 text-indigo-800 border-indigo-200",
  business_rule: "bg-teal-100 text-teal-800 border-teal-200",
  synonym: "bg-gray-100 text-gray-700 border-gray-200",
};

export function StatusBadge({ status }: { status: CandidateStatus }) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border",
        statusStyles[status]
      )}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

export function KindBadge({ kind }: { kind: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border",
        kindStyles[kind] ?? "bg-gray-100 text-gray-700 border-gray-200"
      )}
    >
      {kind.replace(/_/g, " ")}
    </span>
  );
}
