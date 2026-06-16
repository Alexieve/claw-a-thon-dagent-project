import { AppCfg } from "@/shared/config/app";
import type { ApiResponse } from "./types";

export class ApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly timestamp?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function getRequestId(): string | undefined {
  try {
    const raw = localStorage.getItem("dagent-auth");
    return raw ? (JSON.parse(raw)?.state?.userId ?? undefined) : undefined;
  } catch {
    return undefined;
  }
}

export async function post<TResult>(
  payload: Record<string, unknown>,
): Promise<TResult> {
  const rid = getRequestId();
  const res = await fetch(`${AppCfg.apiUrl}/invocations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...payload,
      ...(rid ? { request_id: rid, user_id: rid } : {}),
    }),
  });

  if (!res.ok) {
    throw new ApiError("http_error", `HTTP ${res.status}: ${res.statusText}`);
  }

  const data: ApiResponse<TResult> = await res.json();

  if (data.status === "error") {
    throw new ApiError(
      "api_error",
      data.error ?? "Unknown error",
      data.timestamp,
    );
  }

  return data.result;
}
