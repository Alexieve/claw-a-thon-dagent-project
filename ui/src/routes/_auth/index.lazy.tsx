import { createLazyFileRoute, Link } from "@tanstack/react-router";
import { BookOpen, Brain, CheckSquare, Clock, XCircle, AlertTriangle } from "lucide-react";
import { useListCandidates } from "@/shared/api/hooks";
import type { CandidateStatus } from "@/shared/api/types";

export const Route = createLazyFileRoute("/_auth/")({
  component: Dashboard,
});

interface StatCardProps {
  label: string;
  count: number;
  icon: React.ElementType;
  color: string;
  to: string;
  filterStatus: CandidateStatus | "";
}

function StatCard({ label, count, icon: Icon, color, to }: StatCardProps) {
  return (
    <Link
      to={to}
      className="bg-white rounded-xl border border-gray-200 p-5 hover:shadow-md transition-shadow group"
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-gray-500 mb-1">{label}</p>
          <p className="text-3xl font-bold text-gray-900">{count}</p>
        </div>
        <div className={`p-2.5 rounded-lg ${color}`}>
          <Icon className="w-5 h-5" />
        </div>
      </div>
    </Link>
  );
}

function Dashboard() {
  const allQ = useListCandidates("");

  const candidates = allQ.data?.candidates ?? [];
  const pending = candidates.filter((c) => c.status === "pending_review").length;
  const approved = candidates.filter((c) => c.status === "approved").length;
  const rejected = candidates.filter((c) => c.status === "rejected").length;
  const conflict = candidates.filter((c) => c.status === "conflict").length;

  return (
    <div className="max-w-4xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="text-gray-500 text-sm mt-1">
          Overview of your knowledge base pipeline
        </p>
      </div>

      {allQ.isLoading && (
        <p className="text-sm text-gray-400">Loading stats...</p>
      )}

      {allQ.isError && (
        <div className="px-4 py-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 mb-4">
          Could not load stats — is the API running at http://127.0.0.1:8080?
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard
          label="Pending Review"
          count={pending}
          icon={Clock}
          color="bg-yellow-50 text-yellow-600"
          to="/review"
          filterStatus="pending_review"
        />
        <StatCard
          label="Approved"
          count={approved}
          icon={CheckSquare}
          color="bg-green-50 text-green-600"
          to="/knowledge"
          filterStatus="approved"
        />
        <StatCard
          label="Rejected"
          count={rejected}
          icon={XCircle}
          color="bg-red-50 text-red-600"
          to="/review"
          filterStatus="rejected"
        />
        <StatCard
          label="Conflicts"
          count={conflict}
          icon={AlertTriangle}
          color="bg-orange-50 text-orange-600"
          to="/review"
          filterStatus="conflict"
        />
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h2 className="font-semibold text-gray-800 mb-3">Quick Actions</h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <Link
            to="/teach"
            className="flex items-center gap-3 p-3 rounded-lg border border-gray-200 hover:border-indigo-300 hover:bg-indigo-50 transition-colors"
          >
            <Brain className="w-5 h-5 text-indigo-500" />
            <div>
              <p className="text-sm font-medium text-gray-700">Teach the agent</p>
              <p className="text-xs text-gray-400">Submit free-form text</p>
            </div>
          </Link>
          <Link
            to="/review"
            className="flex items-center gap-3 p-3 rounded-lg border border-gray-200 hover:border-yellow-300 hover:bg-yellow-50 transition-colors"
          >
            <CheckSquare className="w-5 h-5 text-yellow-500" />
            <div>
              <p className="text-sm font-medium text-gray-700">Review candidates</p>
              <p className="text-xs text-gray-400">Approve or reject</p>
            </div>
          </Link>
          <Link
            to="/knowledge"
            className="flex items-center gap-3 p-3 rounded-lg border border-gray-200 hover:border-green-300 hover:bg-green-50 transition-colors"
          >
            <BookOpen className="w-5 h-5 text-green-500" />
            <div>
              <p className="text-sm font-medium text-gray-700">Search knowledge</p>
              <p className="text-xs text-gray-400">Browse approved terms</p>
            </div>
          </Link>
        </div>
      </div>
    </div>
  );
}
