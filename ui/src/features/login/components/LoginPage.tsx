import { useForm } from "@tanstack/react-form";
import { useNavigate } from "@tanstack/react-router";
import { zodValidator } from "@tanstack/zod-form-adapter";
import { z } from "zod";
import { useAuthStore } from "@/store/auth.store";

export function LoginPage() {
  const navigate = useNavigate();
  const login = useAuthStore((s) => s.login);

  const form = useForm({
    defaultValues: { userId: "" },
    validatorAdapter: zodValidator(),
    onSubmit: ({ value }) => {
      const trimmed = value.userId.trim();
      login(trimmed);
      navigate({ to: "/" });
    },
  });

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 w-full max-w-sm p-8 space-y-6">
        <div className="flex justify-center">
          <img src="/dagent-logo.svg" className="h-12 w-auto" alt="Dagent" />
        </div>

        <div className="text-center space-y-1">
          <h1 className="text-xl font-semibold text-gray-900">Sign in</h1>
          <p className="text-sm text-gray-500">Enter your User ID to continue</p>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            e.stopPropagation();
            form.handleSubmit();
          }}
          className="space-y-4"
        >
          <form.Field
            name="userId"
            validators={{
              onChange: z.string().min(1, "User ID is required"),
            }}
          >
            {(field) => (
              <div className="space-y-1">
                <input
                  id="userId"
                  type="text"
                  placeholder="Enter your User ID"
                  required
                  value={field.state.value}
                  onChange={(e) => field.handleChange(e.target.value)}
                  onBlur={field.handleBlur}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                />
                {field.state.meta.errors.length > 0 && (
                  <p className="text-xs text-red-600">
                    {field.state.meta.errors[0]?.toString()}
                  </p>
                )}
              </div>
            )}
          </form.Field>

          <button
            type="submit"
            className="w-full px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
          >
            Login
          </button>
        </form>
      </div>
    </div>
  );
}
