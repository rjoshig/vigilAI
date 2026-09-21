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
  /** What this delivery calls each name the fixed checks look for (Phase 6.21b). */
  layout: LayoutEntry[];
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
  /** For a judgment check: the named values the model may see, and nothing else. */
  value_names: string[];
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
  /**
   * Other configuration paths that also count (Phase 6.15). Spelling and an extra
   * level of nesting are already allowed for; this is for the case no amount of
   * normalising reaches — a customer calling OFAC screening `sdn_screening`.
   */
  alternates: string[];
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

/**
 * What a delivery calls one of the fields the tool checks (Phase 6.14b).
 *
 * Document labels, not data attribute names: a credit date is written "as-of date" on
 * one customer's reports and "cycle date" on another's. `is_builtin` rows are the
 * spellings the tool ships with; they cannot be edited or removed.
 */
export interface FieldLabel {
  id: number;
  canonical: string;
  label: string;
  scope: string;
  scope_label: string;
  is_active: boolean;
  created_by: string;
  is_builtin: boolean;
}

/**
 * A message scheduled at the top of an app (Phase 6.14g).
 *
 * Shown automatically between `starts_at` and `ends_at`, then gone. Not dismissible:
 * a notice somebody scheduled is one they wanted read.
 */
export interface Announcement {
  id: number;
  level: "info" | "warning" | "critical";
  audience: "user" | "admin" | "both";
  message: string;
  starts_at: string;
  ends_at: string;
  is_active: boolean;
  created_by: string;
  /** Whether it is in force at this moment, so the screen need not compare dates. */
  showing_now: boolean;
}

/**
 * What the tool displaced over a period (Phase 6.16).
 *
 * `orders` rather than `runs` is what the hours are based on: an order checked three
 * times displaced one manual check. `hours_per_order` is carried so the report can say
 * which assumption it used.
 */
export interface ValueReport {
  start: string;
  end: string;
  days: number;
  runs: number;
  orders: number;
  customers: number;
  repeat_runs: number;
  hours_per_order: number;
  hours_saved: number;
  working_weeks: number;
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

/** One person's use of the tool over a period (Phase 6.19). */
export interface UserUsage {
  user_id: number;
  name: string;
  username: string;
  /** Every role they hold, weakest first (ADR-049). */
  roles: UserRole[];
  is_active: boolean;
  runs: number;
  finalized: number;
  needs_review: number;
  failed: number;
  /** The artifacts disagreed with the form and nobody has accepted it (ADR-041). */
  held: number;
  cancelled: number;
  in_flight: number;
  orders: number;
  customers: number;
  configurations: number;
  repeat_runs: number;
  mismatch_runs: number;
  /** Tokens their runs sent, and what those cost (Phase 6.21d). */
  tokens: number;
  cost: number;
  cached_calls: number;
  high_findings: number;
  completed_runs: number;
  failure_rate: number;
  held_rate: number;
  repeat_rate: number;
  high_per_run: number;
  first_run_at: string | null;
  last_run_at: string | null;
  /** Sparse: a day they submitted nothing is absent rather than zero. */
  per_day: DayCount[];
}

/** Everyone's use of the tool over one period, with the deployment's own averages. */
export interface UsageByUser {
  start: string;
  end: string;
  days: number;
  users: UserUsage[];
  runs: number;
  failure_rate: number;
  held_rate: number;
  repeat_rate: number;
  periods: number[];
  /** The rate every row's cost was computed at, carried once (Phase 6.21d).
   * Zero means no rate is set and the table shows tokens only. */
  rate_per_million: number;
  currency: string;
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
  /** What it all cost (Phase 6.21d). */
  spend: Spend;
  decisions: Record<string, number>;
}

/** A word the model quoted that would have matched a programme (Phase 6.18f). */
export interface KeywordSuggestion {
  scope_code: string;
  phrase: string;
  /** How many deliveries the model quoted it from. */
  seen: number;
  run_ids: number[];
  already_listed: boolean;
}

/** Every pending suggestion. */
export interface KeywordSuggestions {
  suggestions: KeywordSuggestion[];
}

/** What one prompt's context allowance has left (Phase 6.17b). */
export interface PromptBudget {
  per_field_cap: number;
  block_cap: number;
  used: number;
  remaining: number;
  lines: number;
  /** True when the block is already over and losing its oldest lines. */
  trimmed: boolean;
}

/* ----------------------------------------------------- What a reviewer stops seeing */

/** One recurring finding and what people have decided about it (Phase 6.18a). */
export interface SignatureState {
  signature: string;
  customer_name: string;
  /** The delivery programme. Trust is learned per customer per programme. */
  scope: string;
  rule_ref: string;
  finding_type: string;
  /** What it fired on. Two columns are two signatures, however much they share a rule. */
  element_ref: string;
  /** watching | would_demote | blocked */
  state: string;
  /** One sentence saying why it is in that state. */
  reason: string;
  occurrences: number;
  dismissed: number;
  upheld: number;
  severities: string[];
  /** The runs whose verdicts this rests on. */
  justified_by_run_ids: number[];
}

/** What demotion would do, while it still does nothing (Phase 6.18a, ADR-043). */
export interface DemotionReport {
  counts: Record<string, number>;
  would_demote: SignatureState[];
  blocked: SignatureState[];
  /** True while nothing acts on any of it. */
  shadow: boolean;
}

/* ------------------------------------------------------------ Accounts and login */

export type UserRole = "admin" | "reviewer" | "user";

/**
 * One thing a person may do (ADR-049). Named for the act rather than the screen,
 * because screens get renamed and the question does not change with them. The strings
 * are the API's; the console only ever asks whether one is present.
 */
export type Capability =
  | "view_admin"
  | "approve_training"
  | "manage_rules"
  | "teach_model"
  | "manage_reference"
  | "manage_privacy"
  | "manage_artifacts"
  | "manage_programmes"
  | "manage_meaning"
  | "manage_users"
  | "manage_settings";

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
  /** Every role held, weakest first (ADR-049). Capabilities are the union. */
  roles: UserRole[];
  /**
   * What this person may do, as the API resolved it. Never derived here from the
   * roles: the matrix lives on the server, and a console that reimplemented it would
   * disagree with the API the first time a grant moved — and would disagree by
   * offering a screen that then refuses.
   */
  capabilities: Capability[];
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
  /** Every role held, weakest first. They add up rather than replacing one another. */
  roles: UserRole[];
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
  /**
   * Which roles the account holds. A list and not a choice: they are not exclusive, and
   * a dropdown would say they are — a senior associate is a user *and* a reviewer.
   */
  roles: UserRole[];
}

/** One role and the sentence the API gives for it, shown beside its checkbox. */
export interface RoleChoice {
  role: UserRole;
  description: string;
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
  /**
   * One line the section says about itself, when it has something to say that no
   * single row does. Only **Chat** has one today: the questions asked in the last
   * thirty days, beside the caps they are approaching (Phase 8f).
   */
  note?: string;
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

export type AnchorKind =
  "report_cell" | "report_field" | "osl_section" | "config_path" | "finding" | "rule" | "run";

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
  /** What the overlapping rule is called, so the choice is between named things. */
  name: string;
  summary: string;
  scope: string;
  state: string;
  same: boolean;
}

/** What a candidate would have changed, had it been running already. */
export interface CandidateReplay {
  /** `running` while the worker job is queued; absent once the result has landed. */
  status?: string;
  /** True when the rule was evaluated against the runs, rather than estimated. */
  evaluated?: boolean;
  runs_examined?: number;
  runs_available?: number;
  /** Runs whose stored files could not be read back. */
  unreadable?: number;
  /** The runs the rule would have raised a finding on. */
  would_fire_on?: number[];
  /** A few of the things it would have said, one per run. */
  examples?: string[];
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

/** What the front door made of one sentence (Phase 6.12b). */
export interface FrontDoorResult {
  /** field_constraint · check · compliance_rule · background · unclear. */
  surface: string;
  /** Why the tool read it that way, in one sentence. */
  reason: string;
  confidence: number;
  /** What the tool needs to know, when it could not place the sentence. */
  question: string;
  /** What to do next when nothing was created, or what to notice when it was. */
  note: string;
  /** The candidate, indistinguishable from one the training queue produced. */
  candidate: Candidate | null;
  observation_id: number | null;
  /** The shape synthesis drafted, which is usually the surface. */
  drafted_as: string;
}

/** What an administrator decides about a candidate, beyond approve or reject. */
export interface CandidateApproval {
  note?: string;
  /** Narrower than the candidate proposed, when the administrator wants it so. */
  scope?: string;
  /** Straight to active rather than into shadow. Rarely the right answer. */
  activate_now?: boolean;
  /**
   * What to do about an overlap with a rule that already exists: replace it, or keep
   * both because they cover different ground. Required when the candidate has
   * conflicts; the API refuses without it (Phase 6.11g).
   */
  resolution?: "supersede" | "keep_both";
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
export type VersionKind = "artifact-type" | "programme" | "meaning" | "example";

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

/** A finding a shadow rule produced, as the administrator sees it (ADR-040). */
export interface ShadowFinding {
  id: number;
  run_id: number;
  finding_id: string;
  type: string;
  severity: string;
  title: string;
  detail: string;
  review_status: string;
  review_note: string;
  rule_ref: string;
}

/**
 * One worked example an administrator gives the model (Phase 6.13d, ADR-038).
 *
 * The built-in examples in the prompts are the floor; these are added after them, at
 * most four per stage, narrowest scope first. The answer is validated against the
 * stage's own schema before it is stored, because an example the schema rejects teaches
 * a shape the pipeline cannot parse. An example shows; it is never a rule.
 */
export interface PromptExampleIn {
  stage: string;
  scope: string;
  /** What the model would be shown, keyed by the stage's field names. */
  given: Record<string, string>;
  /** A good answer, in the stage's own JSON shape. */
  answer: Record<string, unknown>;
  note: string;
  is_active: boolean;
  sort_order: number;
}

export interface PromptExample extends PromptExampleIn {
  id: number;
  /** `admin`, or `promoted:<kind>:<id>` when somebody promoted a decision. */
  origin: string;
  created_by: string;
  created_at: string;
  updated_by: string;
  updated_at: string;
}

/** One part of what a stage shows the model. */
export interface ExampleField {
  name: string;
  label: string;
  shape: "line" | "block" | "tag";
}

/** An example that ships inside the prompt, shown read-only above the library. */
export interface BuiltInExample {
  number: number;
  shown: string;
  answer: string;
}

/** A stage an administrator may add examples to. */
export interface ExampleStage {
  stage: string;
  label: string;
  description: string;
  fields: ExampleField[];
  built_in: BuiltInExample[];
  max_examples: number;
}

/** A requirement a reviewer rewrote, offered as an extraction example (ADR-038). */
export interface Correction {
  run_id: number;
  rule_id: string;
  customer: string;
  source_text: string;
  summary: string;
  edited_by: string;
  edited_at: string | null;
  promoted: boolean;
}

/** Turn a decision a person already confirmed into a worked example. */
export interface PromoteExample {
  source: "meaning" | "requirement" | "candidate";
  id: number;
  rule_id?: string;
  scope?: string;
  note?: string;
}

/** What kind of name a layout entry covers. The same closed set the resolver uses. */
export type LayoutKind = "sheet" | "column" | "label";

/**
 * One name a delivery spells differently (Phase 6.21b).
 *
 * Read by the ladder's *fourth* rung, which is the one a person writes: it is reached
 * only after exact, separator-insensitive and same-words matching have all failed, and
 * it never overrules the name actually asked for. Recording one turns a delivery the
 * AI had to reason about into a delivery code resolves, and costs no model call.
 */
export interface LayoutEntry {
  /** Which runs it covers. Empty, or `everywhere`, means all of them. */
  scope: string;
  kind: LayoutKind;
  /** The name the fixed checks ask for, e.g. `Attributes`. */
  wanted: string;
  /** What this delivery calls it. Several, because customers word things differently. */
  names: string[];
  note: string;
  added_by: string;
}

/** A name the AI read for a run, offered to an administrator (ADR-054). */
export interface LayoutSuggestion {
  artifact: string;
  kind: LayoutKind;
  wanted: string;
  found: string;
  /** The AI's own number, already past the floor code applies. */
  confidence: number;
  reason: string;
  /** How many runs met it. Read on every delivery means it is that customer's layout. */
  seen: number;
  run_ids: number[];
  /** True once the artifact type carries it, so an accepted offer stops asking. */
  already_listed: boolean;
}

/** What `GET /admin/layout-suggestions` returns. */
export interface LayoutSuggestions {
  suggestions: LayoutSuggestion[];
}

/** One day's tokens and cost (Phase 6.21d). */
export interface DayCost {
  day: string;
  tokens: number;
  cost: number;
}

/**
 * What some period cost (Phase 6.21d).
 *
 * `rate_per_million` of zero means nobody has set a rate, every money figure here is
 * zero, and the console shows tokens only — a cost built on a rate nobody supplied is
 * a number that gets quoted back as fact.
 */
export interface Spend {
  rate_per_million: number;
  currency: string;
  tokens: number;
  cost: number;
  month_tokens: number;
  month_cost: number;
  /** Warn above this, per month. Never a refusal: the per-run token budget is the
   * only hard stop in the product. Zero switches the band off. */
  monthly_warning: number;
  /** Calls the cache served. They cost nothing and are counted apart. */
  cached_calls: number;
  calls: number;
  per_day: DayCost[];
}

/** What the tool made of one artifact type's samples (Phase 6.21f). */
export interface ArtifactReading {
  key: string;
  label: string;
  sample_count: number;
  sheets: string[];
  /** Names the fixed checks look for that code found, as wanted → what it is here. */
  resolved: Record<string, string>;
  /** Names it looked for and code could not settle. */
  unresolved: string[];
  error: string;
}

/** One pointer, resolved against the samples. */
export interface NamedValueReading {
  name: string;
  description: string;
  found: boolean;
  value: string;
}

/** One check, evaluated over the samples. */
export interface CheckReading {
  name: string;
  expression: string;
  /** `null` when a value it needs was not found, which on a real run is a "could not
   * evaluate" finding rather than a silent skip. */
  passed: boolean | null;
  detail: string;
  shadow: boolean;
}

/**
 * What a setup would do, as far as the samples can say (Phase 6.21f).
 *
 * A rehearsal, not a run: no model is called and nothing is stored, which is what
 * makes it safe to press repeatedly while editing. It answers "is this wired up", not
 * "does it ask the right question".
 */
export interface Rehearsal {
  scope: string;
  artifacts: ArtifactReading[];
  named_values: NamedValueReading[];
  checks: CheckReading[];
  notes: string[];
}
