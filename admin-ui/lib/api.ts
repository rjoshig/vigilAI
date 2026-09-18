/**
 * The typed admin client. Every backend call goes through here (standards/frontend.md).
 */

import type {
  AdminUser,
  Alias,
  ArtifactType,
  ArtifactTypeIn,
  AuthConfig,
  Category,
  Check,
  CheckIn,
  ComplianceRule,
  ConfigChange,
  CurrentUser,
  DraftResponse,
  MaskedColumn,
  NamedValue,
  NamedValueIn,
  NewUser,
  ProviderTestResult,
  Scope,
  ScopeIn,
  Setting,
  SettingGroup,
  TestResult,
  Usage,
} from "@/lib/types";

const BASE = "/api/v1/admin";
const AUTH = "/api/v1/auth";

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

/**
 * The session cookie is HttpOnly and same-origin, since the browser talks to the Next
 * proxy rather than to FastAPI, so fetch sends it without `credentials` being set.
 */
async function request<T>(path: string, init?: RequestInit, base: string = BASE): Promise<T> {
  const response = await fetch(`${base}${path}`, { cache: "no-store", ...init });
  if (!response.ok) throw new ApiError(response.status, await errorDetail(response));
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function json(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

function authRequest<T>(path: string, init?: RequestInit): Promise<T> {
  return request<T>(path, init, AUTH);
}

export const api = {
  /** Read which switches are on. Needs no session, so it is safe as the first call. */
  getAuthConfig: (): Promise<AuthConfig> => authRequest<AuthConfig>("/config"),

  /** Who the API is acting as. 401 when admin auth is on and nobody is signed in. */
  getCurrentUser: (): Promise<CurrentUser> => authRequest<CurrentUser>("/me"),

  /** Sign in. 401 for wrong credentials, 423 while the account is locked out. */
  login: (username: string, password: string): Promise<CurrentUser> =>
    authRequest<CurrentUser>("/login", json("POST", { username, password })),

  /** Sign out, which revokes the session row rather than only dropping the cookie. */
  logout: (): Promise<void> => authRequest<void>("/logout", { method: "POST" }),

  /** Set a new password. 422 when it is too short or unchanged, 401 on a wrong current. */
  changePassword: (
    username: string,
    currentPassword: string,
    newPassword: string
  ): Promise<CurrentUser> =>
    authRequest<CurrentUser>(
      "/change-password",
      json("POST", {
        username,
        current_password: currentPassword,
        new_password: newPassword,
      })
    ),

  /** List every account, active or not, including the placeholder. */
  listUsers: (): Promise<AdminUser[]> => request<AdminUser[]>("/users"),

  /** Create an account. The person must change this first password at sign-in. */
  createUser: (payload: NewUser): Promise<AdminUser> =>
    request<AdminUser>("/users", json("POST", payload)),

  /** Reset someone's password, which forces another change at their next sign-in. */
  resetUserPassword: (id: number, password: string): Promise<AdminUser> =>
    request<AdminUser>(`/users/${id}/password`, json("POST", { password })),

  /** Deactivate or reactivate. 409 when it would leave no active administrator. */
  setUserActive: (id: number, isActive: boolean): Promise<AdminUser> =>
    request<AdminUser>(`/users/${id}/active?is_active=${isActive}`, { method: "POST" }),

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

  /** Every runtime setting, grouped, with its effective value and its source. */
  listSettings: (): Promise<SettingGroup[]> => request<SettingGroup[]>("/settings"),

  /**
   * Override one setting. For a secret the value is the plaintext, which the server
   * encrypts and never returns. 404 unknown key, 422 read-only or out of range, 409
   * when no master key is configured on the server.
   */
  saveSetting: (key: string, value: unknown): Promise<Setting> =>
    request<Setting>("/settings", json("POST", { key, value })),

  /** Remove the override so the setting follows the layer beneath it again. */
  revertSetting: (key: string): Promise<Setting> =>
    request<Setting>(`/settings/${key}`, { method: "DELETE" }),

  /** The recent setting changes, newest first. A secret's values read "(secret)". */
  settingsHistory: (limit = 100): Promise<ConfigChange[]> =>
    request<ConfigChange[]>(`/settings/history?limit=${limit}`),

  /** One real call to the provider, using the settings as they currently resolve. */
  testModel: (): Promise<ProviderTestResult> =>
    request<ProviderTestResult>("/settings/test-model", { method: "POST" }),

  /** Read the dashboard numbers. */
  getUsage: (): Promise<Usage> => request<Usage>("/usage"),
};
