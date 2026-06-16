import { Link, useNavigate } from "@tanstack/react-router";
import {
  BookOpen,
  Brain,
  CheckSquare,
  ChevronDown,
  FileText,
  Home,
  LogOut,
  MessageSquare,
  Plus,
  Search,
} from "lucide-react";
import { ChatSessionSkeleton } from "./ChatSessionSkeleton";
import { useListChatSessions } from "@/shared/api/hooks";
import { cn } from "@/shared/libs/utils";
import { useAuthStore } from "@/store/auth.store";
import { useChatStore } from "@/store/chat.store";
import { useUiStore } from "@/store/ui.store";

const navItems = [
  { to: "/", label: "Dashboard", icon: Home, exact: true },
  { to: "/teach", label: "Teach", icon: Brain, exact: false },
  { to: "/review", label: "Review", icon: CheckSquare, exact: false },
  { to: "/knowledge", label: "Knowledge Base", icon: BookOpen, exact: false },
  { to: "/analyze", label: "Analyze", icon: Search, exact: false },
  { to: "/ingest", label: "Ingest Document", icon: FileText, exact: false },
] as const;

export function Sidebar() {
  const { sidebarOpen } = useUiStore();
  const { userId, logout } = useAuthStore();
  const { activeSessionId, setActiveSession, startNewSession } = useChatStore();
  const { data, isLoading } = useListChatSessions();
  const navigate = useNavigate();

  const sessions = data?.sessions ?? [];
  const visibleSessions = sessions.slice(0, 3);
  const hasMore = sessions.length > 3;

  const handleNewChat = () => {
    startNewSession();
    navigate({ to: "/chat" });
  };

  const handleSessionClick = (id: string) => {
    setActiveSession(id);
    navigate({ to: "/chat" });
  };

  const handleViewMore = () => {
    navigate({ to: "/chat" });
  };

  const handleLogout = () => {
    logout();
    navigate({ to: "/" });
  };

  return (
    <aside
      className={cn(
        "flex flex-col h-full bg-gray-900 text-white transition-all duration-200 shrink-0",
        sidebarOpen ? "w-56" : "w-14",
      )}
    >
      {/* Logo */}
      <div className="h-12 px-3 border-b border-gray-700 flex items-center gap-2.5 shrink-0">
        <Brain className="w-6 h-6 text-indigo-400 shrink-0" />

        {sidebarOpen && <p>DAgent</p>}
      </div>

      {/* Feature nav */}
      <nav className="p-2 space-y-0.5 shrink-0">
        {navItems.map(({ to, label, icon: Icon, exact }) => (
          <Link
            key={to}
            to={to}
            activeOptions={{ exact }}
            className={cn(
              "flex items-center gap-3 px-2 py-2 rounded-lg text-sm transition-colors",
              "text-gray-400 hover:text-white hover:bg-gray-800",
            )}
            activeProps={{
              className: cn(
                "flex items-center gap-3 px-2 py-2 rounded-lg text-sm transition-colors",
                "text-white bg-indigo-600 hover:bg-indigo-500",
              ),
            }}
          >
            <Icon className="w-4 h-4 shrink-0" />
            {sidebarOpen && <span className="truncate">{label}</span>}
          </Link>
        ))}
      </nav>

      <div className="mx-3 border-t border-gray-700" />

      {/* Chat section */}
      <div className="flex-1 min-h-0 overflow-y-auto p-2 space-y-0.5">
        {sidebarOpen && (
          <span className="px-2 py-1 text-xs text-gray-500 font-medium uppercase tracking-wider block">
            Chats
          </span>
        )}

        {/* New Chat button */}
        <button
          onClick={handleNewChat}
          className="w-full flex items-center gap-3 px-2 py-2 rounded-lg text-sm text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
        >
          <Plus className="w-4 h-4 shrink-0" />
          {sidebarOpen && <span className="truncate">New Chat</span>}
        </button>

        {/* Chat session list */}
        {isLoading && <ChatSessionSkeleton sidebarOpen={sidebarOpen} />}

        {visibleSessions.map((session) => (
          <button
            key={session.id}
            onClick={() => handleSessionClick(session.id)}
            className={cn(
              "w-full flex items-center gap-3 px-2 py-2 rounded-lg text-sm text-gray-400 hover:text-white hover:bg-gray-800 transition-colors text-left",
              activeSessionId === session.id && "bg-gray-800 text-white",
            )}
          >
            <MessageSquare className="w-4 h-4 shrink-0" />
            {sidebarOpen && (
              <span className="truncate flex-1">{session.id}</span>
            )}
          </button>
        ))}

        {hasMore && (
          <button
            onClick={handleViewMore}
            className="w-full flex items-center gap-3 px-2 py-2 rounded-lg text-sm text-gray-500 hover:text-white hover:bg-gray-800 transition-colors"
          >
            <ChevronDown className="w-4 h-4 shrink-0" />
            {sidebarOpen && <span className="truncate">View more</span>}
          </button>
        )}
      </div>

      <div className="mx-3 border-t border-gray-700" />

      {/* User bar */}
      <div className="shrink-0 p-2">
        <div className="flex items-center gap-2 px-1">
          <div className="w-7 h-7 rounded-full bg-indigo-600 flex items-center justify-center text-white text-xs font-semibold shrink-0">
            {userId ? userId[0].toUpperCase() : "?"}
          </div>
          {sidebarOpen && (
            <span className="text-sm text-gray-300 truncate flex-1">
              {userId}
            </span>
          )}
          <button
            onClick={handleLogout}
            className="text-gray-400 hover:text-white transition-colors shrink-0"
            aria-label="Logout"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}
