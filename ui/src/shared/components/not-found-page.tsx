import { Link } from "@tanstack/react-router";

export function NotFoundPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <div className="text-center max-w-sm">
        <div className="text-7xl font-bold text-gray-200 mb-4">404</div>
        <h1 className="text-xl font-semibold text-gray-700 mb-2">Page Not Found</h1>
        <p className="text-gray-500 text-sm mb-6">
          The page you're looking for doesn't exist.
        </p>
        <Link
          to="/"
          className="inline-flex items-center px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
        >
          Back to Dashboard
        </Link>
      </div>
    </div>
  );
}
