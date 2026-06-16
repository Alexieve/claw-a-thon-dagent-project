import { Skeleton } from "@/shared/components/ui/skeleton"

const bubbleSizes = [
  { role: "agent", width: "w-64" },
  { role: "user",  width: "w-40" },
  { role: "agent", width: "w-80" },
  { role: "user",  width: "w-52" },
  { role: "agent", width: "w-72" },
  { role: "user",  width: "w-32" },
]

export function ChatHistorySkeleton() {
  return (
    <div className="flex flex-col justify-end h-full space-y-3 pb-2">
      {bubbleSizes.map(({ role, width }, i) => (
        <div key={i} className={role === "user" ? "flex justify-end" : "flex justify-start"}>
          <Skeleton
            className={`${width} h-9 ${
              role === "user"
                ? "rounded-xl rounded-br-sm bg-indigo-200"
                : "rounded-xl rounded-bl-sm bg-muted"
            }`}
          />
        </div>
      ))}
    </div>
  )
}
