import { createFileRoute, redirect } from "@tanstack/react-router";
import { RootLayout } from "@/shared/components/layout/RootLayout";

export const Route = createFileRoute("/_auth")({
  beforeLoad: () => {
    const stored = localStorage.getItem("dagent-auth");
    let userId: string | null = null;
    try {
      userId = stored ? (JSON.parse(stored)?.state?.userId ?? null) : null;
    } catch {
      /* */
    }
    if (!userId) throw redirect({ to: "/login" });
  },
  component: RootLayout,
});
