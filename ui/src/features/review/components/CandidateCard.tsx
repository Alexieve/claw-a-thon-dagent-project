import { CheckCircle, ChevronDown, ChevronUp, Loader2, XCircle } from "lucide-react";
import { useState } from "react";
import { useReviewCandidate } from "@/shared/api/hooks";
import type { Candidate } from "@/shared/api/types";
import { KindBadge, StatusBadge } from "@/shared/components/ui/badge";
import { ConfidenceBar } from "@/shared/components/ui/confidence-bar";
import { ErrorMessage } from "@/shared/components/ui/error-message";

interface CandidateCardProps {
  candidate: Candidate;
}

export function CandidateCard({ candidate: c }: CandidateCardProps) {
  const { mutate, isPending, error } = useReviewCandidate();
  const [editOpen, setEditOpen] = useState(false);
  const [editedDef, setEditedDef] = useState(c.definition);

  const handleDecision = (decision: "approve" | "reject") => {
    mutate({
      candidate_id: c.id,
      decision,
      ...(decision === "approve" && editedDef !== c.definition
        ? { updates: { definition: editedDef } }
        : {}),
    });
  };

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-semibold text-gray-800">{c.name}</span>
          <KindBadge kind={c.kind} />
          <StatusBadge status={c.status} />
        </div>
        <ConfidenceBar value={c.confidence} />
      </div>

      <p className="text-sm text-gray-600">{c.definition}</p>

      {c.paraphrases.length > 0 && (
        <div className="text-xs text-gray-500">
          <span className="font-medium">Also known as: </span>
          {c.paraphrases.join(", ")}
        </div>
      )}

      {(c.domain || c.owner || c.formula) && (
        <div className="flex flex-wrap gap-3 text-xs text-gray-500">
          {c.domain && <span><span className="font-medium">Domain:</span> {c.domain}</span>}
          {c.owner && <span><span className="font-medium">Owner:</span> {c.owner}</span>}
          {c.formula && <span><span className="font-medium">Formula:</span> {c.formula}</span>}
        </div>
      )}

      {c.conflict_with && (
        <div className="px-3 py-2 bg-orange-50 border border-orange-200 rounded text-xs text-orange-700">
          Conflicts with knowledge ID: <code>{c.conflict_with}</code>
        </div>
      )}

      {c.status === "pending_change" && (
        <div className="px-3 py-2 bg-amber-50 border border-amber-200 rounded text-xs text-amber-800 space-y-1">
          {c.change_summary && <p><span className="font-medium">Changes:</span> {c.change_summary}</p>}
          {c.proposed_by && <p><span className="font-medium">Proposed by:</span> {c.proposed_by}</p>}
          {c.original_owner && <p><span className="font-medium">Original owner:</span> {c.original_owner}</p>}
        </div>
      )}

      {c.status === "pending_review" || c.status === "pending_change" || c.status === "conflict" ? (
        <div className="space-y-3 pt-1 border-t border-gray-100">
          <button
            onClick={() => setEditOpen(!editOpen)}
            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700"
          >
            {editOpen ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            Edit definition before approving
          </button>

          {editOpen && (
            <textarea
              value={editedDef}
              onChange={(e) => setEditedDef(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm resize-y focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          )}

          <ErrorMessage error={error} />

          <div className="flex gap-2">
            <button
              onClick={() => handleDecision("approve")}
              disabled={isPending}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 text-white rounded-lg text-xs font-medium hover:bg-green-700 disabled:opacity-60 transition-colors"
            >
              {isPending ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <CheckCircle className="w-3.5 h-3.5" />
              )}
              Approve
            </button>
            <button
              onClick={() => handleDecision("reject")}
              disabled={isPending}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-red-50 text-red-700 border border-red-200 rounded-lg text-xs font-medium hover:bg-red-100 disabled:opacity-60 transition-colors"
            >
              {isPending ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <XCircle className="w-3.5 h-3.5" />
              )}
              Reject
            </button>
          </div>
        </div>
      ) : (
        <div className="pt-1 border-t border-gray-100">
          <p className="text-xs text-gray-400">
            Reviewed · {new Date(c.created_at).toLocaleDateString()}
          </p>
        </div>
      )}
    </div>
  );
}
