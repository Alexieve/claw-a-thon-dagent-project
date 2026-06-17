import { Link } from "@tanstack/react-router";
import { ArrowRight, FileText, Loader2 } from "lucide-react";
import { useState } from "react";
import { useIngestDocument } from "@/shared/api/hooks";
import type { IngestDocumentResult } from "@/shared/api/types";
import { ErrorMessage } from "@/shared/components/ui/error-message";

export function IngestForm() {
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [result, setResult] = useState<IngestDocumentResult | null>(null);
  const { mutate, isPending, error } = useIngestDocument();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    mutate(
      { text, title: title || "Untitled Document" },
      {
        onSuccess: (data) => {
          setResult(data);
          setTitle("");
          setText("");
        },
      }
    );
  };

  return (
    <div className="space-y-6">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Document Title
          </label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Growth Metric Handbook"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Document Text
          </label>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={10}
            placeholder="Paste your document content here. The agent will chunk the text and extract knowledge candidates automatically."
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm resize-y focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
          />
        </div>

        <ErrorMessage error={error} />

        <button
          type="submit"
          disabled={isPending || !text.trim()}
          className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-60 transition-colors"
        >
          {isPending ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <FileText className="w-4 h-4" />
          )}
          {isPending ? "Processing document..." : "Ingest Document"}
        </button>
      </form>

      {result && (
        <div className="bg-green-50 border border-green-200 rounded-xl p-5 space-y-3">
          <h3 className="font-semibold text-green-800 text-sm">Document Ingested</h3>
          <div className="grid grid-cols-3 gap-3 text-center">
            <div className="bg-white rounded-lg border border-green-200 p-3">
              <p className="text-2xl font-bold text-gray-800">{result.chunks.length}</p>
              <p className="text-xs text-gray-500 mt-0.5">Chunks</p>
            </div>
            <div className="bg-white rounded-lg border border-green-200 p-3">
              <p className="text-2xl font-bold text-gray-800">{result.candidates.length}</p>
              <p className="text-xs text-gray-500 mt-0.5">Pending review</p>
            </div>
            <div className="bg-white rounded-lg border border-green-200 p-3">
              <p className="text-xs font-mono text-gray-600 break-all">{result.document_id}</p>
              <p className="text-xs text-gray-500 mt-0.5">Document ID</p>
            </div>
          </div>

          <Link
            to="/review"
            className="inline-flex items-center gap-1.5 text-sm text-indigo-600 hover:text-indigo-800 font-medium"
          >
            Review extracted candidates <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      )}
    </div>
  );
}
