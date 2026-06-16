import { createLazyFileRoute } from "@tanstack/react-router";
import { KnowledgeSearch } from "@/features/knowledge/components/KnowledgeSearch";

export const Route = createLazyFileRoute("/_auth/knowledge")({
  component: KnowledgePage,
});

function KnowledgePage() {
  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Knowledge Base</h1>
        <p className="text-gray-500 text-sm mt-1">
          Browse and search all approved knowledge terms, metrics, and business rules.
        </p>
      </div>

      <KnowledgeSearch />
    </div>
  );
}
