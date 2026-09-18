/**
 * Domain types for the admin surface, mirroring `src/vigilai/api/schemas_admin.py`.
 */

export const REPORT_KINDS = [
  "dirt",
  "field_distribution",
  "state_distribution",
  "score_distribution",
  "counts",
  "cross_tab",
  "billing",
] as const;

export type ReportKind = (typeof REPORT_KINDS)[number];

export const REPORT_LABELS: Record<ReportKind, string> = {
  dirt: "DIRT",
  field_distribution: "Field distribution",
  state_distribution: "State distribution",
  score_distribution: "Score distribution",
  counts: "Counts / number flow",
  cross_tab: "Cross tab",
  billing: "Billing",
};

export type Severity = "high" | "medium" | "low" | "review";
export type LocatorKind = "cell" | "label";
export type CheckKind = "expression" | "judgment";

/**
 * One input the tool accepts: the OSL, the ETL config, or a report type. Which types
 * exist, what they mean, and whether users may upload them is admin data, not code
 * (ADR-020).
 */
export interface ArtifactTypeIn {
  key: string;
  label: string;
  kind: "osl" | "config" | "report";
  description: string;
  /** What the model should pay attention to. Empty leaves the prompts untouched. */
  ai_context: string;
  is_active: boolean;
  is_required: boolean;
  sort_order: number;
}

export interface ArtifactType extends ArtifactTypeIn {
  id: number;
  is_builtin: boolean;
  filename: string;
  has_sample: boolean;
  sheets: string[];
  runs_using: number;
}

/** A delivery programme: AM, AS, Archives, or the catch-all. */
export interface ScopeIn {
  code: string;
  label: string;
  description: string;
  /** Compliance expectations true of every run in the programme, as background. */
  standing_instructions: string;
  is_active: boolean;
  sort_order: number;
}

export interface Scope extends ScopeIn {
  id: number;
  runs_using: number;
}

export interface NamedValueIn {
  name: string;
  report_type: string;
  sheet: string;
  kind: LocatorKind;
  cell: string;
  label: string;
  label_column: number;
  value_column: number;
  description: string;
}

export interface NamedValue extends NamedValueIn {
  id: number;
  resolved: string | null;
  used_by: string[];
}

export interface CheckIn {
  name: string;
  kind: CheckKind;
  expression: string;
  instruction: string;
  reasoning: string;
  severity: Severity;
  scope: string;
  is_active: boolean;
}

export interface Check extends CheckIn {
  id: number;
  version: number;
  created_at: string;
  references: string[];
}

export interface DraftResponse {
  named_values: NamedValueIn[];
  expression: string;
  reasoning: string;
  severity: Severity;
  cached: boolean;
  warnings: string[];
}

export interface TestResult {
  passed: boolean | null;
  detail: string;
  resolved: Record<string, unknown>;
  unresolved: string[];
}

export interface ComplianceRule {
  id: number;
  name: string;
  json_path_contains: string;
  expected_value: unknown;
  scope: string;
  reasoning: string;
  is_active: boolean;
}

export interface Category {
  id: number;
  name: string;
  kinds: string[];
  checked: boolean;
}

export interface Alias {
  id: number;
  canonical_name: string;
  alias: string;
  customer_name: string | null;
}

export interface MaskedColumn {
  id: number;
  pattern: string;
  description: string;
  is_default: boolean;
}

export interface DayCount {
  day: string;
  count: number;
}

export interface Usage {
  runs_total: number;
  runs_per_day: DayCount[];
  duration_p50_ms: number;
  duration_p95_ms: number;
  failure_rate: number;
  tokens_total: number;
  tokens_per_day: DayCount[];
  cache_hit_rate: number;
  json_failure_rate: number;
  false_positive_rate: number;
  findings_by_type: Record<string, number>;
  decisions: Record<string, number>;
}

/* ------------------------------------------------------------ Accounts and login */

export type UserRole = "admin" | "user";

/** Which of the two independent switches are on (ADR-022). Both default to off. */
export interface AuthConfig {
  admin_auth: boolean;
  user_auth: boolean;
}

/**
 * Whoever the API is acting as. There is always one: the seeded placeholder while
 * login is off, the signed-in account otherwise (ADR-022).
 */
export interface CurrentUser {
  id: number;
  name: string;
  email: string;
  role: UserRole;
  is_admin: boolean;
  is_placeholder: boolean;
  must_change_password: boolean;
}

/** An account as the Users screen sees it. Accounts are deactivated, never deleted. */
export interface AdminUser {
  id: number;
  username: string;
  name: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  is_placeholder: boolean;
  must_change_password: boolean;
  last_login_at: string | null;
  locked: boolean;
  created_at: string;
}

/** The fields an administrator fills in to create someone an account. */
export interface NewUser {
  username: string;
  name: string;
  email: string;
  password: string;
  role: UserRole;
}

/* ---------------------------------------------------- Runtime settings (ADR-023) */

export type SettingKind = "bool" | "int" | "str" | "secret" | "enum";

/** Which layer supplied the effective value. Precedence: admin > env > default. */
export type SettingSource = "admin" | "env" | "default";

/** One runtime setting, its effective value, and where that value came from. */
export interface Setting {
  key: string;
  label: string;
  group: string;
  kind: SettingKind;
  help: string;
  source: SettingSource;
  value: unknown;
  /** False for a setting the console cannot change; it is shown read-only. */
  editable: boolean;
  restart: boolean;
  choices: string[];
  minimum: number | null;
  maximum: number | null;
  /** Secrets only: whether one is configured, and its last four characters. */
  is_set: boolean;
  last4: string;
  /** What the value would be if the admin override were removed. */
  fallback: unknown;
  fallback_source: "env" | "default";
}

/** A section of the settings screen, in the order the API returns it. */
export interface SettingGroup {
  name: string;
  settings: Setting[];
}

/** One entry in the settings change history. A secret's values read "(secret)". */
export interface ConfigChange {
  id: number;
  key: string;
  old_value: unknown;
  new_value: unknown;
  changed_by: string;
  changed_at: string;
}

/** What one connection test against the saved model settings found. */
export interface ProviderTestResult {
  ok: boolean;
  provider: string;
  model: string;
  detail: string;
  latency_ms: number;
}
