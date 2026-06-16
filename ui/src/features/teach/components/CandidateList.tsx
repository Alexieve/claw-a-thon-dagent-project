import { Link } from "@tanstack/react-router";
import { ArrowRight, CheckCircle2 } from "lucide-react";
import type { Candidate, Knowledge } from "@/shared/api/types";
import { KindBadge } from "@/shared/components/ui/badge";
import { ConfidenceBar } from "@/shared/components/ui/confidence-bar";

interface CandidateListProps {
  candidates: Candidate[];
  knowledgeCreated?: Knowledge[];
}

export function CandidateList({ candidates, knowledgeCreated = [] }: CandidateListProps) {
  if (candidates.length === 0 && knowledgeCreated.length === 0) {
    return (
      <div className="text-center py-8 text-gray-400 text-sm">
        No candidates extracted from this text.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {knowledgeCreated.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-green-600" />
            <h3 className="text-sm font-medium text-gray-700">
              {knowledgeCreated.length} committed directly to knowledge base
            </h3>
          </div>
          <div className="space-y-2">
            {knowledgeCreated.map((k) => (
              <div
                key={k.id}
                className="bg-green-50 border border-green-200 rounded-lg p-3 space-y-1"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="font-medium text-gray-800 text-sm">{k.name}</span>
                  <KindBadge kind={k.kind} />
                </div>
                <p className="text-xs text-gray-600">{k.canonical_definition}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {candidates.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-gray-700">
              {candidates.length} candidate{candidates.length !== 1 ? "s" : ""} pending review
            </h3>
            <Link
              to="/review"
              className="flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-800"
            >
              Review queue <ArrowRight className="w-3 h-3" />
            </Link>
          </div>
          <div className="space-y-2">
            {candidates.map((c) => (
              <div
                key={c.id}
                className="bg-white border border-gray-200 rounded-lg p-4 space-y-2"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="font-medium text-gray-800 text-sm">{c.name}</span>
                  <KindBadge kind={c.kind} />
                </div>
                <p className="text-xs text-gray-600">{c.definition}</p>
                <ConfidenceBar value={c.confidence} />
                {c.paraphrases.length > 0 && (
                  <p className="text-xs text-gray-400">
                    Also known as: {c.paraphrases.join(", ")}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
