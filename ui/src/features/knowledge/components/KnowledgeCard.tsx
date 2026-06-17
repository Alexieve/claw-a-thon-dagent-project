import { Loader2, Trash2 } from "lucide-react";
import { useDeleteKnowledge } from "@/shared/api/hooks";
import type { Knowledge } from "@/shared/api/types";
import { KindBadge } from "@/shared/components/ui/badge";

interface KnowledgeCardProps {
  item: Knowledge;
}

export function KnowledgeCard({ item: k }: KnowledgeCardProps) {
  const { mutate: deleteKnowledge, isPending } = useDeleteKnowledge();

  const handleDelete = () => {
    const ok = window.confirm(
      `Xóa vĩnh viễn định nghĩa "${k.name}" khỏi từ điển?\nHành động này không thể hoàn tác.`,
    );
    if (ok) deleteKnowledge({ knowledge_id: k.id });
  };

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-3 hover:shadow-sm transition-shadow">
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-semibold text-gray-800">{k.name}</h3>
        <div className="flex items-center gap-2">
          <KindBadge kind={k.kind} />
          <button
            type="button"
            onClick={handleDelete}
            disabled={isPending}
            title="Xóa định nghĩa"
            aria-label={`Xóa định nghĩa ${k.name}`}
            className="text-gray-300 hover:text-red-500 transition-colors disabled:opacity-50"
          >
            {isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Trash2 className="w-4 h-4" />
            )}
          </button>
        </div>
      </div>

      <p className="text-sm text-gray-600">{k.canonical_definition}</p>

      {k.formula && (
        <div className="px-3 py-1.5 bg-gray-50 rounded font-mono text-xs text-gray-700 border border-gray-200">
          {k.formula}
        </div>
      )}

      {k.paraphrases.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {k.paraphrases.map((p, i) => (
            <span
              key={i}
              className="px-2 py-0.5 bg-gray-100 text-gray-600 text-xs rounded"
            >
              {p}
            </span>
          ))}
        </div>
      )}

      {k.conditions.length > 0 && (
        <div className="text-xs text-gray-500">
          <span className="font-medium">Conditions: </span>
          {k.conditions.join("; ")}
        </div>
      )}

      <div className="flex flex-wrap gap-3 text-xs text-gray-400 pt-1 border-t border-gray-100">
        {k.domain && <span>Domain: {k.domain}</span>}
        {k.owner && <span>Owner: {k.owner}</span>}
        <span>Updated: {new Date(k.updated_at).toLocaleDateString()}</span>
      </div>
    </div>
  );
}
