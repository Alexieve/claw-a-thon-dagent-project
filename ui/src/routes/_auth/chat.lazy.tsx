import { createLazyFileRoute } from "@tanstack/react-router";
import { ChatPage } from "@/features/chat/components/ChatPage";

export const Route = createLazyFileRoute("/_auth/chat")({
  component: ChatPage,
});
