import { Skeleton } from "@/shared/components/ui/skeleton"

interface ChatSessionSkeletonProps {
  sidebarOpen: boolean
}

export function ChatSessionSkeleton({ sidebarOpen }: ChatSessionSkeletonProps) {
  return (
    <>
      {[0, 1, 2].map((i) => (
        <div key={i} className="w-full flex items-center gap-3 px-2 py-2">
          <Skeleton className="w-4 h-4 shrink-0 bg-gray-700 rounded-sm" />
          {sidebarOpen && <Skeleton className="h-3.5 flex-1 bg-gray-700" />}
        </div>
      ))}
    </>
  )
}
