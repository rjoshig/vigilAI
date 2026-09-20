/**
 * The typed admin client. Every backend call goes through here (standards/frontend.md).
 */

import type {
  AdminUser,
  Alias,
  Announcement,
  FieldLabel,
  ArtifactType,
  ArtifactTypeIn,
  AuthConfig,
  Candidate,
  CandidateApproval,
  Category,
  Check,
  CheckIn,
  ComplianceRule,
  ConfigChange,
  CurrentUser,
  DraftResponse,
  FrontDoorResult,
  MaskedColumn,
  NamedValue,
  NamedValueIn,
  NewUser,
  Observation,
  ProgrammeRule,
  ProgrammeRuleIn,
  ProviderTestResult,
  Rule,
  RuleActionWord,
  RuleStateChange,
  RuleStateFilter,
  SamplePreview,
  Scope,
  ScopeIn,
  Setting,
  SettingGroup,
  TestResult,
  TrainingConfig,
  Usage,
  DefinitionVersion,
  GuideEntry,
  Correction,
  ExampleStage,
  PromoteExample,
  PromptExample,
  PromptExampleIn,
  VersionKind,
  BulkResult,
  RulesBulkResult,
  MeaningEntry,
  MeaningEntryPatch,
  MeaningSamples,
  ProposeResult,
  ShadowFinding,
} from "@/lib/types";

const BASE = "/api/v1/admin";
const AUTH = "/api/v1/auth";
/** Observations are filed by users, so they live outside the admin prefix. */
const ROOT = "/api/v1";

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

  /**
   * Add one sample to an artifact type. 409 once three are stored, because the
   * fourth is refused rather than silently replacing one.
   */
  addSample(
    key: string,
    file: File,
    label = "",
    notes = "",
    scopeCode = ""
  ): Promise<ArtifactType> {
    const form = new FormData();
    form.set("file", file);
    form.set("label", label);
    form.set("notes", notes);
    form.set("scope_code", scopeCode);
    return request<ArtifactType>(`/artifact-types/${key}/samples`, { method: "POST", body: form });
  },

  /**
   * The download address of one sample. It is a plain URL rather than a fetch, so the
   * browser streams the workbook to disk instead of the page holding it in memory.
   */
  sampleDownloadUrl: (key: string, sampleId: number): string =>
    `${BASE}/artifact-types/${key}/samples/${sampleId}/download`,

  /** What a sample contains, already masked. */
  previewSample: (key: string, sampleId: number): Promise<SamplePreview> =>
    request<SamplePreview>(`/artifact-types/${key}/samples/${sampleId}/preview`),

  /** Replace a type's validation guide; the answer carries the examples filled in. */
  saveGuide: (key: string, entries: GuideEntry[]): Promise<ArtifactType> =>
    request<ArtifactType>(`/artifact-types/${key}/guide`, json("PUT", { entries })),

  /** Relabel a sample, write notes on it, or move it to another programme. */
  updateSample: (
    key: string,
    sampleId: number,
    patch: { label?: string; notes?: string; scope_code?: string }
  ): Promise<ArtifactType> =>
    request<ArtifactType>(`/artifact-types/${key}/samples/${sampleId}`, json("PATCH", patch)),

  /** Remove one sample. */
  deleteSample: (key: string, sampleId: number, confirm: string): Promise<void> =>
    request<void>(
      `/artifact-types/${key}/samples/${sampleId}?confirm=${encodeURIComponent(confirm)}`,
      {
        method: "DELETE",
      }
    ),

  /** Delete an admin-defined type. Refused for a built-in or one a run has used. */
  deleteArtifactType: (key: string, confirm: string): Promise<void> =>
    request<void>(`/artifact-types/${key}?confirm=${encodeURIComponent(confirm)}`, {
      method: "DELETE",
    }),

  /** List the delivery programmes and their standing instructions. */
  listScopes: (): Promise<Scope[]> => request<Scope[]>("/scopes"),

  /** Create or edit a delivery programme. */
  saveScope: (payload: ScopeIn): Promise<Scope> => request<Scope>("/scopes", json("POST", payload)),

  /** Delete a programme. Refused when a run already names it. */
  deleteScope: (code: string, confirm: string): Promise<void> =>
    request<void>(`/scopes/${code}?confirm=${encodeURIComponent(confirm)}`, { method: "DELETE" }),

  /** The rules of one programme, or of every programme when no code is given. */
  listProgrammeRules: (scopeCode = ""): Promise<ProgrammeRule[]> =>
    request<ProgrammeRule[]>(
      `/programme-rules${scopeCode ? `?scope_code=${encodeURIComponent(scopeCode)}` : ""}`
    ),

  /** Add a rule to a programme. 404 when the programme does not exist. */
  createProgrammeRule: (payload: ProgrammeRuleIn): Promise<ProgrammeRule> =>
    request<ProgrammeRule>("/programme-rules", json("POST", payload)),

  /**
   * Edit a rule's wording or strictness. Its state is not edited here: that goes
   * through `actOnRule` with the kind `programme_rule`, so the typed confirmation
   * and the history apply to it like any other rule.
   */
  updateProgrammeRule: (id: number, payload: ProgrammeRuleIn): Promise<ProgrammeRule> =>
    request<ProgrammeRule>(`/programme-rules/${id}`, json("PATCH", payload)),

  /** List the named values, with what each resolves to on the samples. */
  listNamedValues: (): Promise<NamedValue[]> => request<NamedValue[]>("/named-values"),

  /** Create or replace a named value. */
  saveNamedValue: (payload: NamedValueIn): Promise<NamedValue> =>
    request<NamedValue>("/named-values", json("POST", payload)),

  /** Delete a named value. Refused when a check still refers to it. */
  deleteNamedValue: (id: number, confirm: string): Promise<void> =>
    request<void>(`/named-values/${id}?confirm=${encodeURIComponent(confirm)}`, {
      method: "DELETE",
    }),

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
  saveComplianceRule: (payload: Omit<ComplianceRule, "id" | "version">): Promise<ComplianceRule> =>
    request<ComplianceRule>("/compliance-rules", json("POST", payload)),

  /** Delete a compliance rule. */
  deleteComplianceRule: (id: number, confirm: string): Promise<void> =>
    request<void>(`/compliance-rules/${id}?confirm=${encodeURIComponent(confirm)}`, {
      method: "DELETE",
    }),

  /** Reword a compliance rule; each edit bumps its version. */
  updateComplianceRule: (
    id: number,
    payload: Omit<ComplianceRule, "id" | "version">
  ): Promise<ComplianceRule> =>
    request<ComplianceRule>(`/compliance-rules/${id}`, json("PATCH", payload)),

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
  deleteAlias: (id: number, confirm: string): Promise<void> =>
    request<void>(`/aliases/${id}?confirm=${encodeURIComponent(confirm)}`, { method: "DELETE" }),

  /** Every scheduled notice, soonest first, including expired ones. */
  listAnnouncements: (): Promise<Announcement[]> => request<Announcement[]>("/announcements"),

  /** Schedule a notice. The server refuses a sixth, and says why. */
  createAnnouncement: (payload: {
    level: string;
    audience: string;
    message: string;
    starts_at: string;
    ends_at: string;
  }): Promise<Announcement> => request<Announcement>("/announcements", json("POST", payload)),

  /** Switch a notice on or off without losing it. */
  setAnnouncementActive: (id: number, active: boolean): Promise<Announcement> =>
    request<Announcement>(`/announcements/${id}/active?active=${active}`, { method: "POST" }),

  /** Delete a notice. */
  deleteAnnouncement: (id: number, confirm: string): Promise<void> =>
    request<void>(`/announcements/${id}?confirm=${encodeURIComponent(confirm)}`, {
      method: "DELETE",
    }),

  /** What deliveries call the fields the tool checks, built-ins first. */
  listFieldLabels: (): Promise<FieldLabel[]> => request<FieldLabel[]>("/field-labels"),

  /** Add a label for a field the tool checks. */
  createFieldLabel: (payload: {
    canonical: string;
    label: string;
    scope: string;
  }): Promise<FieldLabel> => request<FieldLabel>("/field-labels", json("POST", payload)),

  /** Switch a label on or off, which retires it without losing the row. */
  setFieldLabelActive: (id: number, active: boolean): Promise<FieldLabel> =>
    request<FieldLabel>(`/field-labels/${id}/active?active=${active}`, { method: "POST" }),

  /** Delete a label. */
  deleteFieldLabel: (id: number, confirm: string): Promise<void> =>
    request<void>(`/field-labels/${id}?confirm=${encodeURIComponent(confirm)}`, {
      method: "DELETE",
    }),

  /** List the masked-column patterns. */
  listMaskedColumns: (): Promise<MaskedColumn[]> => request<MaskedColumn[]>("/masked-columns"),

  /** Add a masked-column pattern. */
  createMaskedColumn: (pattern: string, description = ""): Promise<MaskedColumn> =>
    request<MaskedColumn>("/masked-columns", json("POST", { pattern, description })),

  /** Remove a masked-column pattern. */
  deleteMaskedColumn: (id: number, confirm: string): Promise<void> =>
    request<void>(`/masked-columns/${id}?confirm=${encodeURIComponent(confirm)}`, {
      method: "DELETE",
    }),

  /**
   * Delete several rows of one resource under one typed word (ADR-032). Checks and
   * compliance rules are soft-deleted and stay restorable from the Rules screen.
   */
  bulkDelete: (
    resource: "compliance-rules" | "checks" | "named-values" | "aliases" | "masked-columns",
    ids: number[],
    confirm: string
  ): Promise<BulkResult> =>
    request<BulkResult>(`/${resource}/bulk-delete`, json("POST", { ids, confirm })),

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

  /* ----------------------------------------------- The training loop (ADR-021) */

  /**
   * The observations waiting to be looked at. 404 means Train AI mode is off, not
   * that something went wrong, so the caller shows an explanation rather than an
   * error.
   */
  listObservations: (status = "new", kind = ""): Promise<Observation[]> =>
    request<Observation[]>(
      `/observations?status=${encodeURIComponent(status)}${
        kind ? `&kind=${encodeURIComponent(kind)}` : ""
      }`,
      undefined,
      ROOT
    ),

  /**
   * Whether Train AI mode is on. It is read from the shared prefix, the same call the
   * user app makes, so both sidebars say the same thing.
   */
  getTrainingConfig: (): Promise<TrainingConfig> =>
    request<TrainingConfig>("/training/config", undefined, ROOT),

  /**
   * Switch a configuration note off, or back on. Off means it stops reaching the
   * model on the next run; its text is kept, because nothing in the training record
   * is deleted (ADR-024).
   */
  setConfigNoteActive: (id: number, isActive: boolean): Promise<Observation> =>
    request<Observation>(
      `/config-notes/${id}/active?is_active=${isActive}`,
      { method: "POST" },
      ROOT
    ),

  /** Turn an observation down. The reason is shown to whoever wrote it. */
  rejectObservation: (id: number, reason: string): Promise<Observation> =>
    request<Observation>(`/observations/${id}/reject`, json("POST", { reason })),

  /**
   * Ask the model to draft rules from the selected observations. This is the only
   * call that reaches the model here, and it writes nothing that runs.
   */
  synthesize: (observationIds: number[]): Promise<Candidate[]> =>
    request<Candidate[]>("/candidates", json("POST", { observation_ids: observationIds })),

  /** The candidates waiting for a decision. */
  listCandidates: (status = "draft"): Promise<Candidate[]> =>
    request<Candidate[]>(`/candidates?status=${encodeURIComponent(status)}`),

  /** Fill in what this candidate would have changed on runs that already happened. */
  replayCandidate: (id: number): Promise<Candidate> =>
    request<Candidate>(`/candidates/${id}/replay`, { method: "POST" }),

  /** Approve a candidate. It becomes a rule in shadow unless `activate_now` is set. */
  approveCandidate: (id: number, payload: CandidateApproval = {}): Promise<Candidate> =>
    request<Candidate>(`/candidates/${id}/approve`, json("POST", payload)),

  /** Turn a candidate down, with the reason the author of its observations sees. */
  rejectCandidate: (id: number, reason: string): Promise<Candidate> =>
    request<Candidate>(`/candidates/${id}/reject`, json("POST", { reason })),

  /**
   * Say what you want checked in your own words and let the tool place it on the
   * surface that already runs it (Phase 6.12b). What comes back is an ordinary
   * candidate, an offer to the surface that holds background, or a question.
   */
  tellTheTool: (statement: string, scope: string): Promise<FrontDoorResult> =>
    request<FrontDoorResult>("/front-door", json("POST", { statement, scope })),

  /** Every rule, in the order the server sorted them. Filtered to active by default. */
  listRules: (state: RuleStateFilter = "active", search = ""): Promise<Rule[]> =>
    request<Rule[]>(
      `/rules?state=${encodeURIComponent(state)}&search=${encodeURIComponent(search)}`
    ),

  /**
   * Change a rule's state. `confirm` has to be the action word: the API enforces it
   * with a 400, because a rule change reaches every future run.
   */
  actOnRule: (
    ruleKind: string,
    id: number,
    action: RuleActionWord,
    confirm: string,
    note = ""
  ): Promise<Rule> =>
    request<Rule>(`/rules/${ruleKind}/${id}/action`, json("POST", { action, confirm, note })),

  /** One state change on several rules, under one typed action word. */
  actOnRules: (
    items: { rule_kind: string; id: number }[],
    action: RuleActionWord,
    confirm: string,
    note = ""
  ): Promise<RulesBulkResult> =>
    request<RulesBulkResult>("/rules/bulk", json("POST", { items, action, confirm, note })),

  /** Meaning entries of one scope (Phase 6.10). */
  listMeaning: (scopeCode = ""): Promise<MeaningEntry[]> =>
    request<MeaningEntry[]>(`/meaning?scope_code=${encodeURIComponent(scopeCode)}`),

  /** The samples an interview on this scope reads, and what is missing. */
  meaningSamples: (scopeCode = ""): Promise<MeaningSamples> =>
    request<MeaningSamples>(`/meaning/samples?scope_code=${encodeURIComponent(scopeCode)}`),

  /** Run the mapping interview: one cached model call per OSL section. */
  proposeMeaning: (scopeCode = ""): Promise<ProposeResult> =>
    request<ProposeResult>("/meaning/propose", json("POST", { scope_code: scopeCode })),

  /** Write a requirement mapping by hand; it starts confirmed. */
  createMeaning: (payload: Record<string, unknown>): Promise<MeaningEntry> =>
    request<MeaningEntry>("/meaning", json("POST", payload)),

  /** Correct an entry, decide it, or both. */
  updateMeaning: (id: number, patch: MeaningEntryPatch): Promise<MeaningEntry> =>
    request<MeaningEntry>(`/meaning/${id}`, json("PATCH", patch)),

  /** Confirm, reject or delete several entries; delete needs the typed word. */
  bulkMeaning: (
    ids: number[],
    action: "confirm" | "reject" | "delete",
    confirm = ""
  ): Promise<{ changed: number; missing: number[] }> =>
    request<{ changed: number; missing: number[] }>(
      "/meaning/bulk",
      json("POST", { ids, action, confirm })
    ),

  /** Every state this rule has moved between, with who moved it. */
  ruleHistory: (ruleKind: string, id: number): Promise<RuleStateChange[]> =>
    request<RuleStateChange[]>(`/rules/${ruleKind}/${id}/history`),

  /** What a shadow rule found, which no reviewer sees (ADR-040). */
  shadowFindings: (ruleKind: string, id: number): Promise<ShadowFinding[]> =>
    request<ShadowFinding[]>(`/rules/${ruleKind}/${id}/shadow-findings`),

  /**
   * Say a shadow finding is not a real problem. The ordinary finding review, reached from
   * the admin console because reviewers never see the finding; this is what makes a shadow
   * rule's precision knowable before it is activated.
   */
  dismissShadowFinding: (findingId: number, note: string): Promise<ShadowFinding> =>
    request<ShadowFinding>(
      `/findings/${findingId}`,
      json("PATCH", { review_status: "false_positive", review_note: note }),
      ROOT
    ),

  // --- the administrator's worked examples (Phase 6.13d, ADR-038) ---------------------

  /** The stages an example can be added to, with the examples that ship in the prompt. */
  listExampleStages: (): Promise<ExampleStage[]> => request<ExampleStage[]>("/example-stages"),

  /** The stored examples, for one stage or for all of them. */
  listExamples: (stage?: string): Promise<PromptExample[]> =>
    request<PromptExample[]>(`/examples${stage ? `?stage=${encodeURIComponent(stage)}` : ""}`),

  /** Add an example. The API validates the answer against the stage's own schema. */
  saveExample: (payload: PromptExampleIn): Promise<PromptExample> =>
    request<PromptExample>("/examples", json("POST", payload)),

  /** Edit an example, or activate and deactivate one. */
  patchExample: (id: number, payload: Partial<PromptExampleIn>): Promise<PromptExample> =>
    request<PromptExample>(`/examples/${id}`, json("PATCH", payload)),

  /** Requirements reviewers rewrote, which is the model being told it read wrongly. */
  listCorrections: (): Promise<Correction[]> => request<Correction[]>("/corrections"),

  /** Turn a decision somebody already confirmed into a worked example. */
  promoteExample: (payload: PromoteExample): Promise<PromptExample> =>
    request<PromptExample>("/examples/promote", json("POST", payload)),

  /** The last ten versions of an artifact type or a programme's rules, newest first. */
  listVersions: (kind: VersionKind, key: string): Promise<DefinitionVersion[]> =>
    request<DefinitionVersion[]>(`/versions/${kind}/${encodeURIComponent(key)}`),

  /**
   * Put an old version back as a new one. `confirm` has to be the word `revert`;
   * the API enforces it with a 400.
   */
  revertVersion: (
    kind: VersionKind,
    key: string,
    version: number,
    confirm: string
  ): Promise<DefinitionVersion> =>
    request<DefinitionVersion>(
      `/versions/${kind}/${encodeURIComponent(key)}/${version}/revert`,
      json("POST", { confirm })
    ),
};
