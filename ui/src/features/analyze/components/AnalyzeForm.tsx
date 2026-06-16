import { Loader2, Sparkles } from "lucide-react";
import { useState } from "react";
import { useAnalyzeText } from "@/shared/api/hooks";
import type { AnalyzeTextResult } from "@/shared/api/types";
import { ErrorMessage } from "@/shared/components/ui/error-message";

interface AnalyzeFormProps {
  onResult: (result: AnalyzeTextResult) => void;
}

export function AnalyzeForm({ onResult }: AnalyzeFormProps) {
  const [text, setText] = useState("");
  const { mutate, isPending, error } = useAnalyzeText();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    mutate(text, { onSuccess: onResult });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Text to Analyze
        </label>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={5}
          placeholder="Enter text containing business terms to analyze. E.g. 'So sánh FPU, NPU, NAU và NPR trong quý này.'"
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
          <Sparkles className="w-4 h-4" />
        )}
        {isPending ? "Analyzing..." : "Analyze Text"}
      </button>
    </form>
  );
}
