import { useForm } from "@tanstack/react-form";
import { Loader2, Send } from "lucide-react";
import { useTeachText } from "@/shared/api/hooks";
import type { TeachTextResult } from "@/shared/api/types";
import { ErrorMessage } from "@/shared/components/ui/error-message";

interface TeachFormProps {
  onSuccess: (result: TeachTextResult) => void;
}

export function TeachForm({ onSuccess }: TeachFormProps) {
  const { mutate, isPending, error } = useTeachText();

  const form = useForm({
    defaultValues: { text: "", stakeholder: "", team: "" },
    onSubmit: ({ value }) => {
      mutate(value, {
        onSuccess: (result) => {
          onSuccess(result);
          form.reset();
        },
      });
    },
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        form.handleSubmit();
      }}
      className="space-y-4"
    >
      <form.Field
        name="text"
        validators={{
          onChange: ({ value }) =>
            !value || value.trim().length < 10
              ? "Text must be at least 10 characters"
              : undefined,
        }}
      >
        {(field) => (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Knowledge Text
            </label>
            <textarea
              value={field.state.value}
              onChange={(e) => field.handleChange(e.target.value)}
              onBlur={field.handleBlur}
              rows={5}
              placeholder="E.g. 'FPU là user có first payment. Team Growth hay gọi là paid user đầu tiên.'"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm resize-y focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
            {field.state.meta.errors.length > 0 && (
              <p className="text-xs text-red-600 mt-1">
                {String(field.state.meta.errors[0])}
              </p>
            )}
          </div>
        )}
      </form.Field>

      <div className="grid grid-cols-2 gap-4">
        <form.Field
          name="stakeholder"
          validators={{
            onChange: ({ value }) =>
              !value?.trim() ? "Stakeholder is required" : undefined,
          }}
        >
          {(field) => (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Stakeholder
              </label>
              <input
                type="text"
                value={field.state.value}
                onChange={(e) => field.handleChange(e.target.value)}
                onBlur={field.handleBlur}
                placeholder="e.g. Linh"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              />
              {field.state.meta.errors.length > 0 && (
                <p className="text-xs text-red-600 mt-1">
                  {String(field.state.meta.errors[0])}
                </p>
              )}
            </div>
          )}
        </form.Field>

        <form.Field
          name="team"
          validators={{
            onChange: ({ value }) =>
              !value?.trim() ? "Team is required" : undefined,
          }}
        >
          {(field) => (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Team
              </label>
              <input
                type="text"
                value={field.state.value}
                onChange={(e) => field.handleChange(e.target.value)}
                onBlur={field.handleBlur}
                placeholder="e.g. Growth"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              />
              {field.state.meta.errors.length > 0 && (
                <p className="text-xs text-red-600 mt-1">
                  {String(field.state.meta.errors[0])}
                </p>
              )}
            </div>
          )}
        </form.Field>
      </div>

      <ErrorMessage error={error} />

      <button
        type="submit"
        disabled={isPending}
        className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-60 transition-colors"
      >
        {isPending ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <Send className="w-4 h-4" />
        )}
        {isPending ? "Processing..." : "Teach Agent"}
      </button>
    </form>
  );
}
