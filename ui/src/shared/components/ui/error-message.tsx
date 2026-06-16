interface ErrorMessageProps {
  error: Error | null | undefined;
}

export function ErrorMessage({ error }: ErrorMessageProps) {
  if (!error) return null;
  return (
    <div className="px-4 py-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
      {error.message}
    </div>
  );
}
