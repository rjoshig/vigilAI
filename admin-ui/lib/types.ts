/**
 * Domain types for the admin surface, mirroring `src/greenlight_ai/api/schemas_admin.py`.
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

/**
 * One uploaded example of an artifact type. A type holds up to three, because real
 * report layouts vary between customers and a single sample hides that (ADR-021).
 */
export interface Sample {
  id: number;
  label: string;
  /** The programme this sample belongs to; "" for a global one. */
  scope_code: string;
  filename: string;
  sheets: string[];
  size_bytes: number;
  notes: string;
  uploaded_by: string;
  created_at: string;
}

/** One populated cell of a sample, addressed the way a named value addresses it. */
export interface CellPreview {
  cell: string;
  value: string;
  label: string;
  row: number;
  column: number;
}

export interface SheetPreview {
  name: string;
  rows: number;
  columns: number;
  cells: CellPreview[];
}

/** What a sample contains. Values arrive already masked, exactly as at parse time. */
export interface SamplePreview {
  sample_id: number;
  filename: string;
  sheets: SheetPreview[];
}

export interface ArtifactType extends ArtifactTypeIn {
  id: number;
  is_builtin: boolean;
  /** Up to three. */
  samples: Sample[];
  /** Every sheet name across all of the samples, merged. */
  sheets: string[];
  runs_using: number;
  /** The validation guide, examples filled from the samples. */
  guide: GuideEntry[];
  /** The newest definition version; zero before the first save (ADR-029). */
  version: number;
}

/** A delivery programme: AM, AS, Archives, or the catch-all. */
export interface ScopeIn {
  code: string;
  label: string;
  description: string;
  /** Compliance expectations true of every run in the programme, as background. */
  standing_instructions: string;
  /**
   * Words that mark a delivery as this programme's. The pipeline greps the OSL, the
   * configuration, and the report headers for them, and raises a finding when a run
   * is declared as a programme none of whose words appear.
   */
  keywords: string[];
  is_active: boolean;
  sort_order: number;
  /**
   * Whether a run in this programme needs a second person to approve before it can be
   * frozen, when the reviewer waved through something this programme treats as
   * serious. Off by default, and inert while login is off, because both people would
   * then be the same placeholder account (ADR-036).
   */
  second_approver: boolean;
}

export interface Scope extends ScopeIn {
  id: number;
  runs_using: number;
  /** The newest version of its rule set; zero before the first save (ADR-029). */
  version: number;
}

/**
 * How serious a breach of a programme rule is. The model names what a delivery
 * breaks; code turns the strictness into the finding's severity (must is high,
 * should medium, advisory low).
 */
export type Strictness = "must" | "should" | "advisory";

export const STRICTNESS_LEVELS: Strictness[] = ["must", "should", "advisory"];

/** What an administrator writes to create or edit a programme rule. */
export interface ProgrammeRuleIn {
  scope_code: string;
  title: string;
  text: string;
  strictness: Strictness;
  sort_order?: number;
}

/**
 * One rule a programme's deliveries are read against. Its state is changed through
 * the rules screen's action endpoint with the kind `programme_rule`, not here.
 */
export interface ProgrammeRule extends ProgrammeRuleIn {
  id: number;
  sort_order: number;
  state: string;
  origin: string;
  created_by: string;
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
  /** Bumped on every edit. */
  version: number;
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

/* ------------------------------------------------- The training loop (ADR-021) */

export type AnchorKind = "report_cell" | "report_field" | "osl_section" | "config_path" | "finding";

/**
 * What an observation points at. The anchor is what makes reliable synthesis
 * possible; the sentence alone is a guess.
 */
export interface Anchor {
  kind: AnchorKind;
  artifact: string;
  sheet: string;
  cell: string;
  field: string;
  reference: string;
  value: string;
}

/** Whether Train AI mode is on. Read under `/api/v1`, because the user app reads it too. */
export interface TrainingConfig {
  enabled: boolean;
}

/** One earlier wording of a configuration note, kept when it is edited (ADR-024). */
export interface ObservationRevision {
  version: number;
  statement: string;
  at: string;
  by: string;
}

/** Something a reviewer knows, in their own words, against something they selected. */
export interface Observation {
  id: number;
  kind: "reconciliation" | "field_constraint" | "correction" | "note" | "config_note";
  anchors: Anchor[];
  statement: string;
  expectation: string;
  severity_hint: Severity;
  scope_hint: "global" | "customer" | "programme";
  run_id: number | null;
  finding_id: number | null;
  author: string;
  status: string;
  status_note: string;
  candidate_id: number | null;
  customer_name: string;
  scope_code: string;
  version: number;
  editable: boolean;
  /**
   * For a configuration note only: the configuration it follows, whether it still
   * reaches the model, and the earlier wordings. Empty on every other kind (ADR-024).
   */
  configuration_id: string;
  is_active: boolean;
  revisions: ObservationRevision[];
  created_at: string;
  synthesized_at: string | null;
}

/** An overlap between a candidate and a rule that already runs. */
export interface CandidateConflict {
  rule_kind: string;
  id: number;
  summary: string;
  scope: string;
  state: string;
  same: boolean;
}

/** What a candidate would have changed, had it been running already. */
export interface CandidateReplay {
  runs_examined?: number;
  related_findings?: number;
  previously_dismissed?: number;
  note?: string;
}

/** A rule the model drafted. It does not run; only an approved rule does. */
export interface Candidate {
  id: number;
  name: string;
  target_kind: string;
  body: Record<string, unknown>;
  reasoning: string;
  severity: string;
  scope: string;
  status: string;
  admin_note: string;
  source_observation_ids: number[];
  model_used: string;
  prompt_version: string;
  conflicts: CandidateConflict[];
  replay: CandidateReplay;
  created_by: string;
  decided_by: string;
  created_at: string;
}

/** What an administrator decides about a candidate, beyond approve or reject. */
export interface CandidateApproval {
  note?: string;
  /** Narrower than the candidate proposed, when the administrator wants it so. */
  scope?: string;
  /** Straight to active rather than into shadow. Rarely the right answer. */
  activate_now?: boolean;
}

export type RuleState = "active" | "shadow" | "disabled" | "deleted" | "draft";

/** The state filter also accepts "all", which is not a state a rule can be in. */
export type RuleStateFilter = RuleState | "all";

export type RuleActionWord = "enable" | "disable" | "delete" | "restore" | "activate";

/** One rule on the rules screen, whatever its origin. */
export interface Rule {
  id: number;
  rule_kind: string;
  name: string;
  summary: string;
  reasoning: string;
  severity: string;
  scope: string;
  state: string;
  origin: string;
  fired: number;
  dismissed: number;
  dismissal_rate: number;
  last_fired_at: string | null;
  source_observation_ids: number[];
  deleted_at: string | null;
  restorable_until: string | null;
}

/** One move a rule made between states, with who did it. */
export interface RuleStateChange {
  id: number;
  from_state: string;
  to_state: string;
  note: string;
  actor: string;
  at: string;
}

/** Which definitions keep ten versions with revert (ADR-029). */
export type VersionKind = "artifact-type" | "programme" | "meaning";

/** One retained version of an artifact type or a programme's rule set. */
export interface DefinitionVersion {
  version: number;
  summary: string;
  reverted_from: number | null;
  created_by: string;
  created_at: string;
  snapshot: Record<string, unknown>;
}

/** Where a validation-guide entry points in the report (Phase 6.8b). */
export interface GuideLocator {
  kind: "cell" | "label";
  sheet: string;
  cell: string;
  label: string;
  label_column: number;
  value_column: number;
}

/** The entry's value in one stored sample, filled by the server. */
export interface GuideExample {
  sample_id: number;
  label: string;
  value: string;
}

export type GuideComparison = "" | "equals" | "reconciles";

/**
 * One line of a validation guide: what a cell means and where it answers to. An
 * entry with a config path and a comparison that resolves on a sample also becomes a
 * shadow check (ADR-029).
 */
export interface GuideEntry {
  id: string;
  locator: GuideLocator;
  meaning: string;
  osl_section: string;
  osl_phrase: string;
  config_path: string;
  validate: string;
  comparison: GuideComparison;
  tolerance: number;
  examples: GuideExample[];
}

/** What a bulk delete did (ADR-032). */
export interface BulkResult {
  deleted: number;
  missing: number[];
}

/** What a bulk rule action did. */
export interface RulesBulkResult {
  changed: number;
  failed: string[];
}

/** Where in a report a requirement is evidenced (Phase 6.10). */
export interface MeaningReportCell {
  report_key: string;
  sheet: string;
  kind: "cell" | "label";
  cell: string;
  label: string;
  label_column: number;
  value_column: number;
}

export type MeaningStatus = "proposed" | "open" | "confirmed" | "rejected";

/**
 * One requirement mapping: OSL section → configuration block → report cells. The
 * model proposes, a person confirms, code compiles (ADR-033).
 */
export interface MeaningEntry {
  id: number;
  scope_code: string;
  key: string;
  osl_section: string;
  osl_phrase: string;
  requirement_text: string;
  config_path: string;
  report_cells: MeaningReportCell[];
  meaning: string;
  validate: string;
  comparison: "" | "equals" | "reconciles";
  tolerance: number;
  examples: { sample_id: number; label: string; value: string }[];
  compliance_suggestion: { name: string; json_path_contains: string; reasoning: string } | null;
  status: MeaningStatus;
  question: string;
  note: string;
  confidence: number;
  proposed_by: string;
  confirmed_by: string;
  confirmed_at: string | null;
  updated_at: string;
  compiled_check: boolean;
  compiled_compliance: boolean;
}

export interface MeaningEntryPatch {
  status?: MeaningStatus;
  osl_section?: string;
  osl_phrase?: string;
  requirement_text?: string;
  config_path?: string;
  report_cells?: MeaningReportCell[];
  meaning?: string;
  validate?: string;
  comparison?: "" | "equals" | "reconciles";
  tolerance?: number;
  note?: string;
  drop_compliance_suggestion?: boolean;
}

export interface MeaningSamples {
  samples: {
    artifact_key: string;
    label: string;
    sample_id: number;
    scope_code: string;
    filename: string;
  }[];
  missing: string[];
}

export interface ProposeResult {
  sections: number;
  proposed: number;
  open: number;
  updated: number;
  skipped_confirmed: number;
  calls: number;
  cached: number;
}
