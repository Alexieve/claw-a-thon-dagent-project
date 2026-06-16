import { createLazyFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { TeachSessionPanel } from "@/features/teach-session/components/TeachSessionPanel";
import { CandidateList } from "@/features/teach/components/CandidateList";
import { TeachForm } from "@/features/teach/components/TeachForm";
import type { TeachTextResult } from "@/shared/api/types";

export const Route = createLazyFileRoute("/_auth/teach")({
  component: TeachPage,
});

type Tab = "quick" | "session";

function TeachPage() {
  const [activeTab, setActiveTab] = useState<Tab>("quick");
  const [lastResult, setLastResult] = useState<TeachTextResult | null>(null);

  const handleTabChange = (tab: Tab) => {
    setActiveTab(tab);
    setLastResult(null);
  };

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Teach the Agent</h1>
        <p className="text-gray-500 text-sm mt-1">
          Submit business knowledge directly or start a guided session where the agent asks clarifying questions.
        </p>
      </div>

      <div className="flex gap-1 border-b border-gray-200">
        {(["quick", "session"] as Tab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => handleTabChange(tab)}
            className={
              activeTab === tab
                ? "px-4 py-2 text-sm font-medium text-indigo-600 border-b-2 border-indigo-600 -mb-px"
                : "px-4 py-2 text-sm font-medium text-gray-500 hover:text-gray-700 border-b-2 border-transparent -mb-px transition-colors"
            }
          >
            {tab === "quick" ? "Quick Teach" : "Teaching Session"}
          </button>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-5">
        {activeTab === "quick" ? (
          <TeachForm onSuccess={setLastResult} />
        ) : (
          <TeachSessionPanel />
        )}
      </div>

      {activeTab === "quick" && lastResult && (
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="font-semibold text-gray-800 mb-4">Extracted Knowledge</h2>
          <CandidateList
            candidates={lastResult.candidates}
            knowledgeCreated={lastResult.knowledge_created}
          />
        </div>
      )}
    </div>
  );
}
