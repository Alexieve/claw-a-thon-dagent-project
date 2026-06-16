import { createLazyFileRoute } from "@tanstack/react-router";
import { LoginPage } from "@/features/login/components/LoginPage";

export const Route = createLazyFileRoute("/login")({
  component: LoginPage,
});
