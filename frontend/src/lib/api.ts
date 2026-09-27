// Thin client for the FastAPI envelope. Types are hand-written until M2, when they will be
// generated from the OpenAPI schema.

export class ApiError extends Error {
  constructor(
    public readonly errorCode: string,
    message: string,
    public readonly details: Record<string, unknown> = {},
    public readonly requestId: string | null = null,
  ) {
    super(message);
  }
}

type Envelope<T> =
  | { success: true; data: T; meta: { request_id: string | null } }
  | {
      success: false;
      error_code: string;
      message: string;
      details?: Record<string, unknown>;
      request_id: string | null;
    };

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError("NETWORK_ERROR", "Could not reach the server. Check your connection.");
  }
  let body: Envelope<T>;
  try {
    body = (await response.json()) as Envelope<T>;
  } catch {
    throw new ApiError("BAD_RESPONSE", `The server returned an unexpected response (${response.status}).`);
  }
  if (!body.success) {
    throw new ApiError(body.error_code, body.message, body.details ?? {}, body.request_id);
  }
  return body.data;
}

export type Unit = {
  code: string;
  display_name: string;
  dimension: string;
  is_canonical: boolean;
  decimal_places: number;
  aliases: string[];
};

export type TemplateParameter = {
  name: string;
  label: string;
  dimension: string;
  required: boolean;
  default: string | null;
  canonical_unit: string | null;
};

export type Template = {
  id: string;
  version: number;
  name: string;
  category: string;
  expression: string;
  expression_display: string;
  output_unit: string;
  output_unit_display: string;
  description: string;
  parameters: TemplateParameter[];
};

export type Calculation = {
  value: string;
  value_raw: string;
  display: string;
  unit: string;
  unit_display: string;
  expression: string;
  substituted: string;
  inputs: {
    name: string;
    label: string;
    value: string;
    unit: string | null;
    formula_value: string;
    formula_unit: string | null;
    source: string;
  }[];
  steps: { kind: string; text: string }[];
  template_id: string | null;
  template_version: number | null;
  engine_version: string;
  check: string;
};

export type ParamValue = { value: string; unit: string | null };
