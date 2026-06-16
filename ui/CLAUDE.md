# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
bun run dev        # dev server at http://localhost:5177
bun run build      # tsc -b && vite build → dist/
bun run lint       # eslint .
bun run preview    # serve dist/
bun run clean      # rm -rf dist node_modules
```

> The backend must be running separately: `cd ../api && python3 main.py` (listens on `http://127.0.0.1:8080`).

## Tech Stack

- Vite 5 + React 19, TypeScript strict mode
- TanStack Router (file-based, auto-generated route tree)
- TanStack Query — server state
- TanStack Form + Zod adapter — form validation
- Zustand — client UI state (sidebar open/close only)
- Tailwind CSS v4 (CSS-first config via `@theme` in CSS, no `tailwind.config.*`)
- lucide-react — icons
- vite-plugin-svgr — SVG imports as React components

## API

All requests go to `POST /invocations` with `{ "action": "<name>", ...payload }`.

| Action              | Mutation / Query |
|---------------------|-----------------|
| `teach_text`        | mutation        |
| `list_candidates`   | query           |
| `review_candidate`  | mutation        |
| `search_knowledge`  | query           |
| `analyze_text`      | mutation        |
| `ingest_document`   | mutation        |

API response envelope: `{ status, timestamp, session_id, result, error? }`. The `post<T>()` helper in `src/shared/api/client.ts` unwraps this and throws `ApiError` on `status === "error"` or non-2xx HTTP.

## Directory Structure

```
src/
├── features/
│   ├── teach/components/     # TeachForm, CandidateList
│   ├── review/components/    # ReviewQueue, CandidateCard
│   ├── knowledge/components/ # KnowledgeSearch, KnowledgeCard
│   ├── analyze/components/   # AnalyzeForm, AnalysisResult
│   └── ingest/components/    # IngestForm
├── shared/
│   ├── api/
│   │   ├── types.ts          # All TS types (Candidate, Knowledge, payloads, results)
│   │   ├── client.ts         # post<T>(payload) → T, throws ApiError
│   │   └── hooks.ts          # TanStack Query hooks per action + queryKeys
│   ├── components/
│   │   ├── layout/           # RootLayout (shell), Sidebar
│   │   └── ui/               # badge, confidence-bar, empty-state, error-message
│   ├── config/app.ts         # AppCfg: apiUrl, env, isProd
│   ├── hooks/use-debounce.ts
│   └── libs/utils.ts         # cn() (clsx + tailwind-merge)
├── store/ui.store.ts          # Zustand: sidebarOpen / toggleSidebar
└── routes/                   # TanStack Router file-based routes
    ├── __root.tsx             # RootLayout + RouterDevtools (DEV only)
    ├── index.lazy.tsx         # Dashboard
    ├── teach.lazy.tsx
    ├── review.lazy.tsx
    ├── knowledge.lazy.tsx
    ├── analyze.lazy.tsx
    └── ingest.lazy.tsx
```

## Key Patterns

### API usage

```ts
import { post } from "@/shared/api/client";
const result = await post<SearchKnowledgeResult>({ action: "search_knowledge", query: "FPU" });
```

### TanStack Query hooks

```ts
import { useSearchKnowledge, useTeachText } from "@/shared/api/hooks";
const { data, isLoading } = useSearchKnowledge("FPU");
const { mutate, isPending } = useTeachText();
```

Mutations that write candidates invalidate `["candidates"]`; `useReviewCandidate` also invalidates `["knowledge"]`.

### Routing

`routeTree.gen.ts` is **auto-generated** by `@tanstack/router-plugin` — never edit it manually. It regenerates on `bun run dev` or `bun run build`. Add new pages by creating a file in `src/routes/`.

### State management

- Server state → TanStack Query (all API data)
- UI state → Zustand `useUiStore` (sidebar only)
- Form state → TanStack Form with `@tanstack/zod-form-adapter`

### Loading states

Use `Skeleton` from `@/shared/components/ui/skeleton` for all data-fetch loading states — list items, message history, cards. `Loader2` (spinner) is reserved for inline actions only: button submitting, send icon, optimistic mutation indicators (e.g. the chat "Thinking…" bubble). Never use `Loader2` in place of content that has a known shape.

## Environment Variables

Actual vars used (see `src/shared/config/app.ts`):

| Variable       | Default                    | Purpose                        |
|----------------|----------------------------|--------------------------------|
| `VITE_API_URL` | `http://127.0.0.1:8080`    | Agent API base URL             |
| `VITE_ENV`     | `development`              | `development` / `production`   |

> `env.example` is stale — it references Firebase/analytics vars that are not used. The working defaults are already in `.env`.
