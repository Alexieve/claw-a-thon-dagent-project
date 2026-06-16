import { createLazyFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import type { AnalyzeTextResult } from "@/shared/api/types";
import { AnalysisResult } from "@/features/analyze/components/AnalysisResult";
import { AnalyzeForm } from "@/features/analyze/components/AnalyzeForm";

export const Route = createLazyFileRoute("/_auth/analyze")({
  component: AnalyzePage,
});

function AnalyzePage() {
  const [result, setResult] = useState<AnalyzeTextResult | null>(null);

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Analyze Text</h1>
        <p className="text-gray-500 text-sm mt-1">
          Paste text to see which terms are known, pending, in conflict, or unknown.
        </p>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <AnalyzeForm onResult={setResult} />
      </div>

      {result && <AnalysisResult result={result} />}
    </div>
  );
}
