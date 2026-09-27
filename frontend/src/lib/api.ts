// Client for the FastAPI envelope. Response types come from the generated OpenAPI schema
// (npm run gen:api), so the frontend cannot drift from the backend.
import type { components } from "./api-schema";

type Schemas = components["schemas"];
export type Me = Schemas["MeOut"];
export type Project = Schemas["ProjectOut"];
export type ProjectCreate = Schemas["ProjectCreate"];
export type ProjectPatch = Schemas["ProjectPatch"];
export type Dashboard = Schemas["DashboardOut"];
export type Option = Schemas["Option"];
export type WorkCategory = Schemas["CategoryOut"];
export type Organization = Schemas["OrganizationOut"];
export type SystemInfo = Schemas["SystemInfo"];
export type Unit = Schemas["UnitOut"];
export type Template = Schemas["TemplateOut"];
export type Calculation = Schemas["CalculationOut"];
export type ParamValue = { value: string; unit: string | null };
export type Estimate = Schemas["EstimateOut"];
export type Version = Schemas["VersionOut"];
export type VersionSummary = Schemas["VersionSummaryOut"];
export type Section = Schemas["SectionOut"];
export type Item = Schemas["ItemOut"];
export type Line = Schemas["LineOut"];
export type LineCalculation = Schemas["LineCalculationOut"];
export type Parameter = Schemas["ParameterOut"];
export type Extraction = Schemas["ExtractionOut"];
export type ExtractedComponent = Schemas["ComponentOut"];
export type ExtractedParam = Schemas["ExtractedParamOut"];
export type ConfirmResult = Schemas["ConfirmOut"];

export class ApiError extends Error {
  constructor(
    public readonly errorCode: string,
    message: string,
    public readonly status: number = 0,
    public readonly details: Record<string, unknown> = {},
    public readonly requestId: string | null = null,
  ) {
    super(message);
  }

  /** Field-level messages from a VALIDATION_ERROR, keyed by field name. */
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    const fields = this.details.fields;
    if (Array.isArray(fields)) {
      for (const f of fields as { field: string; message: string }[]) {
        out[f.field] = f.message.replace(/^Value error, /, "");
      }
    }
    if (typeof this.details.field === "string") out[this.details.field] = this.message;
    return out;
  }
}

type ErrorBody = {
  success: false;
  error_code: string;
  message: string;
  details?: Record<string, unknown>;
  request_id: string | null;
};

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match?.[1] ? decodeURIComponent(match[1]) : null;
}

let refreshing: Promise<boolean> | null = null;

/** One refresh at a time, shared by every request that hit an expired access token. */
function refreshSession(): Promise<boolean> {
  refreshing ??= fetch("/api/v1/auth/refresh", { method: "POST", credentials: "same-origin" })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

function goToLogin() {
  if (typeof window === "undefined") return;
  const here = window.location.pathname + window.location.search;
  if (!window.location.pathname.startsWith("/login")) {
    // This module is not a component, so the Next.js router is not available here.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign(`/login?next=${encodeURIComponent(here)}`);
  }
}

async function send(path: string, init: RequestInit): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  if (method !== "GET" && method !== "HEAD") {
    const token = readCookie("eai_csrf");
    if (token) headers.set("X-CSRF-Token", token);
  }
  return fetch(`/api/v1${path}`, { ...init, method, headers, credentials: "same-origin" });
}

export async function apiRaw<T>(
  path: string,
  init: RequestInit = {},
  options: { redirectOn401?: boolean } = {},
): Promise<{ data: T; meta: Record<string, unknown> }> {
  let response: Response;
  try {
    response = await send(path, init);
    if (response.status === 401) {
      const body = (await response.clone().json().catch(() => null)) as ErrorBody | null;
      if (body?.error_code === "TOKEN_EXPIRED" && (await refreshSession())) {
        response = await send(path, init);
      }
    }
  } catch {
    throw new ApiError("NETWORK_ERROR", "Could not reach the server. Check your connection.");
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiError("BAD_RESPONSE", `The server returned an unexpected response (${response.status}).`, response.status);
  }
  const envelope = body as { success: boolean; data?: T; meta?: Record<string, unknown> };
  if (!envelope.success) {
    const err = body as ErrorBody;
    if (response.status === 401 && options.redirectOn401 !== false) goToLogin();
    throw new ApiError(err.error_code, err.message, response.status, err.details ?? {}, err.request_id);
  }
  return { data: envelope.data as T, meta: envelope.meta ?? {} };
}

export async function api<T>(path: string, init: RequestInit = {}, options?: { redirectOn401?: boolean }): Promise<T> {
  return (await apiRaw<T>(path, init, options)).data;
}

export const post = <T>(path: string, body?: unknown, options?: { redirectOn401?: boolean }) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }, options);
export const patch = <T>(path: string, body: unknown) =>
  api<T>(path, { method: "PATCH", body: JSON.stringify(body) });
export const del = <T>(path: string) => api<T>(path, { method: "DELETE" });
