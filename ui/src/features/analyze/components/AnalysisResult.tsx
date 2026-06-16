import { AlertTriangle, BookOpen, Clock, HelpCircle } from "lucide-react";
import type { AnalyzeTextResult } from "@/shared/api/types";
import { KindBadge, StatusBadge } from "@/shared/components/ui/badge";

interface AnalysisResultProps {
  result: AnalyzeTextResult;
}

function SectionHeader({
  icon: Icon,
  title,
  count,
  color,
}: {
  icon: React.ElementType;
  title: string;
  count: number;
  color: string;
}) {
  return (
    <div className={`flex items-center gap-2 mb-3 pb-2 border-b ${color}`}>
      <Icon className="w-4 h-4" />
      <h3 className="text-sm font-semibold">{title}</h3>
      <span className="ml-auto text-xs opacity-70">{count} item{count !== 1 ? "s" : ""}</span>
    </div>
  );
}

export function AnalysisResult({ result }: AnalysisResultProps) {
  return (
    <div className="space-y-5">
      {result.answer && (
        <div className="px-4 py-3 bg-indigo-50 border border-indigo-100 rounded-xl text-sm text-indigo-800">
          {result.answer}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Known */}
        <div className="bg-white border border-green-200 rounded-xl p-4">
          <SectionHeader
            icon={BookOpen}
            title="Known"
            count={result.known.length}
            color="border-green-200 text-green-700"
          />
          {result.known.length === 0 ? (
            <p className="text-xs text-gray-400">No known terms found.</p>
          ) : (
            <div className="space-y-2">
              {result.known.map((k) => (
                <div key={k.id} className="text-sm">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-gray-800">{k.name}</span>
                    <KindBadge kind={k.kind} />
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5">{k.canonical_definition}</p>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Pending */}
        <div className="bg-white border border-yellow-200 rounded-xl p-4">
          <SectionHeader
            icon={Clock}
            title="Pending Review"
            count={result.pending.length}
            color="border-yellow-200 text-yellow-700"
          />
          {result.pending.length === 0 ? (
            <p className="text-xs text-gray-400">No pending terms found.</p>
          ) : (
            <div className="space-y-2">
              {result.pending.map((c) => (
                <div key={c.id} className="text-sm">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-gray-800">{c.name}</span>
                    <StatusBadge status={c.status} />
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5">{c.definition}</p>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Conflicts */}
        <div className="bg-white border border-orange-200 rounded-xl p-4">
          <SectionHeader
            icon={AlertTriangle}
            title="Conflicts"
            count={result.conflicts.length}
            color="border-orange-200 text-orange-700"
          />
          {result.conflicts.length === 0 ? (
            <p className="text-xs text-gray-400">No conflicts found.</p>
          ) : (
            <div className="space-y-2">
              {result.conflicts.map((c) => (
                <div key={c.id} className="text-sm">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-gray-800">{c.name}</span>
                    <StatusBadge status={c.status} />
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5">{c.definition}</p>
                  {c.conflict_with && (
                    <p className="text-xs text-orange-600 mt-0.5">
                      Conflicts with: <code>{c.conflict_with}</code>
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Unknown */}
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <SectionHeader
            icon={HelpCircle}
            title="Unknown Terms"
            count={result.unknown.length}
            color="border-gray-200 text-gray-600"
          />
          {result.unknown.length === 0 ? (
            <p className="text-xs text-gray-400">No unknown terms detected.</p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {result.unknown.map((term, i) => (
                <span
                  key={i}
                  className="px-2 py-0.5 bg-gray-100 text-gray-700 text-xs rounded font-mono"
                >
                  {term}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
