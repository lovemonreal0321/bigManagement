/**
 * HTTP client for the FastAPI backend.
 *
 * Every failure comes back as an `ApiError` carrying the backend's stable
 * `code` and a message already written for a human (spec §58), so callers
 * render `error.message` directly and branch on `error.code` when they need to
 * (e.g. offering "Reconnect" for an expired calendar).
 */

import { readStoredValue, writeStoredValue } from "./browser-hooks";
import type { AuthUser } from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8100/api/v1";

export const TOKEN_KEY = "jscc.token";

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;
  readonly retryable: boolean;

  constructor(
    message: string,
    options: {
      code?: string;
      status?: number;
      details?: Record<string, unknown>;
      retryable?: boolean;
    } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.code = options.code ?? "error";
    this.status = options.status ?? 0;
    this.details = options.details ?? {};
    this.retryable = options.retryable ?? false;
  }

  /** Field-level messages from a 422, for inline form errors. */
  get fieldErrors(): Record<string, string> {
    const fields = this.details.fields;
    return typeof fields === "object" && fields !== null
      ? (fields as Record<string, string>)
      : {};
  }
}

// --------------------------------------------------------------------------
// Token storage
// --------------------------------------------------------------------------

export function getToken(): string | null {
  return readStoredValue(TOKEN_KEY);
}

export function setToken(token: string | null) {
  // Goes through the store helper so `useStoredValue` subscribers re-render.
  writeStoredValue(TOKEN_KEY, token);
}

/** Called when a request comes back 401, so the shell can bounce to /login. */
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

// --------------------------------------------------------------------------
// Request
// --------------------------------------------------------------------------

export type QueryValue =
  | string
  | number
  | boolean
  | null
  | undefined
  | (string | number)[];

export function buildQuery(params?: Record<string, QueryValue>): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    if (Array.isArray(value)) {
      // Repeated parameters: ?person_ids=a&person_ids=b
      for (const item of value) search.append(key, String(item));
    } else {
      search.append(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  params?: Record<string, QueryValue>;
  signal?: AbortSignal;
}

export async function request<T>(
  path: string,
  { method = "GET", body, params, signal }: RequestOptions = {},
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}${buildQuery(params)}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    // The backend being down is by far the most common cause here, and it is
    // worth saying so plainly rather than showing "Failed to fetch".
    throw new ApiError(
      "Cannot reach the server. Make sure the backend is running on " +
        `${API_BASE.replace("/api/v1", "")}.`,
      { code: "network_error", retryable: true },
    );
  }

  if (response.status === 401) {
    setToken(null);
    onUnauthorized?.();
    throw new ApiError("Your session has expired. Please sign in again.", {
      code: "unauthorized",
      status: 401,
    });
  }

  if (response.status === 204) return undefined as T;

  let payload: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const envelope = (payload as { error?: Record<string, unknown> })?.error;
    throw new ApiError(
      (envelope?.message as string) ??
        "Something went wrong. Please try again.",
      {
        code: (envelope?.code as string) ?? "error",
        status: response.status,
        details: (envelope?.details as Record<string, unknown>) ?? {},
        retryable: Boolean(envelope?.retryable),
      },
    );
  }

  return payload as T;
}

export const api = {
  get: <T>(path: string, params?: Record<string, QueryValue>) =>
    request<T>(path, { params }),
  post: <T>(path: string, body?: unknown, params?: Record<string, QueryValue>) =>
    request<T>(path, { method: "POST", body, params }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

// --------------------------------------------------------------------------
// Auth
// --------------------------------------------------------------------------

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: AuthUser;
}

export async function login(
  username: string,
  password: string,
): Promise<LoginResponse> {
  const result = await request<LoginResponse>("/auth/login", {
    method: "POST",
    body: { username, password },
  });
  setToken(result.access_token);
  return result;
}

export async function fetchMe(): Promise<AuthUser> {
  return request<AuthUser>("/auth/me");
}

export function logout() {
  setToken(null);
}
