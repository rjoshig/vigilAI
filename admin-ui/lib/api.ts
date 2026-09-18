/**
 * The typed admin client. Every backend call goes through here (standards/frontend.md).
 */

import type {
  Alias,
  ArtifactType,
  ArtifactTypeIn,
  Category,
  Check,
  CheckIn,
  ComplianceRule,
  DraftResponse,
  MaskedColumn,
  NamedValue,
  NamedValueIn,
  Scope,
  ScopeIn,
  TestResult,
  Usage,
} from "@/lib/types";

const BASE = "/api/v1/admin";

/** An error carrying the status, so a caller can tell 409 from 422 from a timeout. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail || `request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function errorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail) && detail.length > 0) {
        const first: unknown = detail[0];
        if (first && typeof first === "object" && "msg" in first) {
          return String((first as { msg: unknown }).msg);
        }
      }
      return JSON.stringify(detail);
    }
  } catch {
    // A non-JSON body has no detail to read.
  }
  return response.statusText;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { cache: "no-store", ...init });
  if (!response.ok) throw new ApiError(response.status, await errorDetail(response));
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function json(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

export const api = {
  /** List every input the tool accepts, active or not, in display order. */
  listArtifactTypes: (): Promise<ArtifactType[]> => request<ArtifactType[]>("/artifact-types"),

  /** Create a report type, or edit any type's meaning, guidance, or state. */
  saveArtifactType: (payload: ArtifactTypeIn): Promise<ArtifactType> =>
    request<ArtifactType>("/artifact-types", json("POST", payload)),

  /** Upload or replace the sample workbook for one artifact type. */
  uploadSample(key: string, file: File): Promise<ArtifactType> {
    const form = new FormData();
    form.set("file", file);
    return request<ArtifactType>(`/artifact-types/${key}/sample`, { method: "POST", body: form });
  },

  /** Delete an admin-defined type. Refused for a built-in or one a run has used. */
  deleteArtifactType: (key: string): Promise<void> =>
    request<void>(`/artifact-types/${key}`, { method: "DELETE" }),

  /** List the delivery programmes and their standing instructions. */
  listScopes: (): Promise<Scope[]> => request<Scope[]>("/scopes"),

  /** Create or edit a delivery programme. */
  saveScope: (payload: ScopeIn): Promise<Scope> => request<Scope>("/scopes", json("POST", payload)),

  /** Delete a programme. Refused when a run already names it. */
  deleteScope: (code: string): Promise<void> =>
    request<void>(`/scopes/${code}`, { method: "DELETE" }),

  /** List the named values, with what each resolves to on the samples. */
  listNamedValues: (): Promise<NamedValue[]> => request<NamedValue[]>("/named-values"),

  /** Create or replace a named value. */
  saveNamedValue: (payload: NamedValueIn): Promise<NamedValue> =>
    request<NamedValue>("/named-values", json("POST", payload)),

  /** Delete a named value. Refused when a check still refers to it. */
  deleteNamedValue: (id: number): Promise<void> =>
    request<void>(`/named-values/${id}`, { method: "DELETE" }),

  /** List every check, active or not. */
  listChecks: (): Promise<Check[]> => request<Check[]>("/checks"),

  /** Create a check, or save a new version of an existing one. */
  saveCheck: (payload: CheckIn): Promise<Check> => request<Check>("/checks", json("POST", payload)),

  /** Enable or disable a check without touching old findings. */
  setCheckActive: (id: number, isActive: boolean): Promise<Check> =>
    request<Check>(`/checks/${id}/active?is_active=${isActive}`, { method: "PATCH" }),

  /** The one LLM call in the admin flow: propose a check from a description. */
  draftCheck: (description: string, reportTypes: string[] = []): Promise<DraftResponse> =>
    request<DraftResponse>(
      "/checks/draft",
      json("POST", { description, report_types: reportTypes })
    ),

  /** Evaluate an expression against the uploaded samples. Never calls the model. */
  testExpression: (expression: string): Promise<TestResult> =>
    request<TestResult>("/checks/test", json("POST", { expression })),

  /** List the must-have compliance rules. */
  listComplianceRules: (): Promise<ComplianceRule[]> =>
    request<ComplianceRule[]>("/compliance-rules"),

  /** Create or replace a compliance rule. */
  saveComplianceRule: (payload: Omit<ComplianceRule, "id">): Promise<ComplianceRule> =>
    request<ComplianceRule>("/compliance-rules", json("POST", payload)),

  /** Delete a compliance rule. */
  deleteComplianceRule: (id: number): Promise<void> =>
    request<void>(`/compliance-rules/${id}`, { method: "DELETE" }),

  /** List the reverse-pass categories. */
  listCategories: (): Promise<Category[]> => request<Category[]>("/categories"),

  /** Create or replace a reverse-pass category. */
  saveCategory: (payload: Omit<Category, "id">): Promise<Category> =>
    request<Category>("/categories", json("POST", payload)),

  /** List the attribute aliases. */
  listAliases: (): Promise<Alias[]> => request<Alias[]>("/aliases"),

  /** Add an attribute alias. */
  createAlias: (payload: Omit<Alias, "id">): Promise<Alias> =>
    request<Alias>("/aliases", json("POST", payload)),

  /** Delete an attribute alias. */
  deleteAlias: (id: number): Promise<void> => request<void>(`/aliases/${id}`, { method: "DELETE" }),

  /** List the masked-column patterns. */
  listMaskedColumns: (): Promise<MaskedColumn[]> => request<MaskedColumn[]>("/masked-columns"),

  /** Add a masked-column pattern. */
  createMaskedColumn: (pattern: string, description = ""): Promise<MaskedColumn> =>
    request<MaskedColumn>("/masked-columns", json("POST", { pattern, description })),

  /** Remove a masked-column pattern. */
  deleteMaskedColumn: (id: number): Promise<void> =>
    request<void>(`/masked-columns/${id}`, { method: "DELETE" }),

  /** Read the dashboard numbers. */
  getUsage: (): Promise<Usage> => request<Usage>("/usage"),
};
