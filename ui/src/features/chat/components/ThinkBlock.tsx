import { Brain, ChevronDown } from "lucide-react";

interface ThinkBlockProps {
  blocks: string[];
}

export function ThinkBlock({ blocks }: ThinkBlockProps) {
  return (
    <div className="space-y-1 mb-1">
      {blocks.map((block, i) => (
        <details
          key={i}
          className="border border-gray-200 rounded-lg bg-gray-50/60 text-xs text-gray-500 group"
        >
          <summary className="flex items-center gap-1.5 px-3 py-1.5 cursor-pointer select-none list-none">
            <Brain className="w-3.5 h-3.5 text-gray-400" />
            <span className="italic text-gray-400">Thought process</span>
            <ChevronDown className="w-3 h-3 ml-auto text-gray-300 group-open:rotate-180 transition-transform" />
          </summary>
          <p className="px-3 pb-2 pt-1 whitespace-pre-wrap leading-relaxed text-gray-500 border-t border-gray-200">
            {block}
          </p>
        </details>
      ))}
    </div>
  );
}
