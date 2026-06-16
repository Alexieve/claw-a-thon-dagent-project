import { createLazyFileRoute } from "@tanstack/react-router";
import { IngestForm } from "@/features/ingest/components/IngestForm";

export const Route = createLazyFileRoute("/_auth/ingest")({
  component: IngestPage,
});

function IngestPage() {
  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Ingest Document</h1>
        <p className="text-gray-500 text-sm mt-1">
          Paste document text to auto-chunk and extract knowledge candidates in bulk.
        </p>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <IngestForm />
      </div>
    </div>
  );
}
