import { useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { Check, Copy } from "lucide-react";
import { cn } from "@/shared/libs/utils";
import "katex/dist/katex.min.css";

interface MarkdownContentProps {
  content: string;
  className?: string;
}

/** Fenced code block: dark panel with a language label + copy button + horizontal scroll
 * (whitespace-pre + overflow-x-auto so long lines like SQL scroll instead of wrapping
 * at hyphens — e.g. DATE '2025-12-01' stays on one line). */
function CodeBlock({ language, code }: { language?: string; code: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable (e.g. non-secure context) — ignore */
    }
  };

  return (
    <div className="not-prose my-2 overflow-hidden rounded-lg border border-gray-700 bg-gray-900">
      <div className="flex items-center justify-between border-b border-gray-700 bg-gray-800 px-3 py-1.5">
        <span className="font-mono text-[10px] uppercase tracking-wider text-gray-400">
          {language || "code"}
        </span>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1 text-[11px] text-gray-400 transition-colors hover:text-gray-100"
        >
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
          {copied ? "Đã copy" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto p-3 text-xs leading-relaxed">
        <code className="whitespace-pre font-mono text-gray-100">{code}</code>
      </pre>
    </div>
  );
}

function childrenToText(children: React.ReactNode): string {
  if (typeof children === "string") return children;
  if (Array.isArray(children)) return children.map(childrenToText).join("");
  return "";
}

const components: Components = {
  // pre just unwraps; the styled container lives in CodeBlock (rendered by `code`).
  pre: ({ children }) => <>{children}</>,
  code: ({ className, children }) => {
    const match = /language-(\w+)/.exec(className || "");
    const text = childrenToText(children).replace(/\n$/, "");
    const isBlock = match !== null || text.includes("\n");
    if (!isBlock) {
      return (
        <code className="rounded bg-gray-200/70 px-1 py-0.5 font-mono text-[0.85em] text-gray-800">
          {children}
        </code>
      );
    }
    return <CodeBlock language={match?.[1]} code={text} />;
  },
  // GFM table → bordered, scrollable, zebra-striped.
  table: ({ children }) => (
    <div className="not-prose my-2 overflow-x-auto rounded-lg border border-gray-200">
      <table className="w-full border-collapse text-xs">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-gray-100">{children}</thead>,
  th: ({ children }) => (
    <th className="border-b border-gray-200 px-3 py-2 text-left font-semibold text-gray-700">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border-b border-gray-100 px-3 py-2 align-top text-gray-700">
      {children}
    </td>
  ),
  tbody: ({ children }) => (
    <tbody className="[&>tr:nth-child(even)]:bg-gray-50/60">{children}</tbody>
  ),
};

export function MarkdownContent({ content, className }: MarkdownContentProps) {
  return (
    <div
      className={cn(
        "prose prose-sm max-w-none",
        "prose-p:my-1 prose-headings:mt-3 prose-headings:mb-1.5 prose-headings:font-semibold",
        "prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5",
        "prose-code:before:content-none prose-code:after:content-none",
        "prose-a:text-indigo-600 prose-a:no-underline hover:prose-a:underline",
        "prose-blockquote:border-l-indigo-300 prose-blockquote:text-gray-600 prose-blockquote:not-italic prose-blockquote:font-normal",
        "prose-hr:my-3",
        className,
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[
          // throwOnError/strict false: cong thuc co chu tieng Viet trong \text{}
          // (vd "Số lượng") khong lam KaTeX bao loi do; van render cau truc, browser
          // fallback font cho glyph tieng Viet.
          [rehypeKatex, { throwOnError: false, strict: false }],
        ]}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
