import { Outlet } from "@tanstack/react-router";
import { Menu } from "lucide-react";
import { useUiStore } from "@/store/ui.store";
import { Sidebar } from "./Sidebar";

export function RootLayout() {
  const { toggleSidebar } = useUiStore();

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <Sidebar />

      <div className="flex flex-col flex-1 overflow-hidden min-w-0">
        <header className="h-12 border-b bg-white flex items-center px-4 gap-3 shrink-0 shadow-sm">
          <button
            onClick={toggleSidebar}
            className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors"
            aria-label="Toggle sidebar"
          >
            <Menu className="w-4 h-4 text-gray-600" />
          </button>
          <span className="text-sm text-gray-500 font-medium">Knowledge Agent Demo</span>
        </header>

        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
