import { createLazyFileRoute } from "@tanstack/react-router";
import { ReviewQueue } from "@/features/review/components/ReviewQueue";

export const Route = createLazyFileRoute("/_auth/review")({
  component: ReviewPage,
});

function ReviewPage() {
  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Review Candidates</h1>
        <p className="text-gray-500 text-sm mt-1">
          Approve or reject knowledge candidates extracted from stakeholder inputs.
        </p>
      </div>

      <ReviewQueue />
    </div>
  );
}
