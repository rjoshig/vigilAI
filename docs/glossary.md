# Glossary

Domain and project terms for a new developer. Definitions follow [`design.md`](design.md);
where a term maps to code, the subpackage is named.

## Inputs

| Term | Meaning |
| --- | --- |
| **OSL** | The requirement spec for one fulfillment job: a Word document on a standard template, English text plus criteria tables. **The source of truth.** Parsed by `parsers/osl`. |
| **Config** | The ETL configuration JSON for the job. Schema varies by job. Split into logical **config blocks** with JSON paths by `parsers/config`. |
| **Reports** | The Excel outputs of the ETL: **DIRT**, field distribution, state distribution, counts, score distribution, cross tabs. One fixed parser per **report type** in `parsers/reports`. |
| **DIRT** | The main output report: per-attribute statistics (min, max, mean, nulls) for the delivered data. Its **second tab** holds sample rows and may contain real PII. |
| **Sample tab / sample rows** | Example records in the DIRT report. Masked at parse time; never sent to the LLM. |
| **Waterfall** | The ordered sequence of filter steps the ETL applies (e.g. age, then score, then tag). Each step has a count; counts must reconcile across reports. |
| **Attribute** | A field / column in the delivered data. Names can differ across OSL, config, and reports → **attribute alias** table. |

## Rules and reconciliation

| Term | Meaning |
| --- | --- |
| **Canonical rule** | The one common format both OSL requirements and config rules are converted into (`rules/`). Fields: `rule_id`, `source`, `req_type`, `waterfall_step`, `applies_to`, `conditions` + `logic`, `action` / `else_action`, `source_ref`, `source_text`, `confidence`. |
| **req_type** | The requirement kind, which decides normalization, comparison, and report check: `criteria`, `geography`, `value_set`, `attributes`, `waterfall`, `quantity`, `other`. |
| **Requirement** | A canonical rule whose `source` is `osl` (or `user` after an edit). |
| **Config element** | What one config block does, expressed in requirement vocabulary (stage 3). Table `config_elements`; `is_technical` marks blocks with no business meaning. |
| **Trace** | A link between a requirement and a config element with a verdict (`implemented`, `partial`, `contradicts`, `not related`), reason, and confidence (stage 4). Users can fix a wrong link and re-check. |
| **Three-way reconciliation** | OSL → config → reports, plus the scoped reverse pass config → OSL. A finding names which leg broke. |
| **Reverse pass** | Checking config elements back against the OSL, scoped to three categories: filters / select criteria, model data (attributes), fixed compliance rules. |
| **Compliance rule** | A rule that must be present in every config in scope even if the OSL never mentions it. Maintained in the admin-ui. |
| **Derived check** | The report expectation a rule implies (`age < 21 → reject` ⇒ `accepts.age.min >= 21`). Fixed code per operator. |
| **Golden set** | 10–20 synthetic OSLs with known-correct rules; the extraction accuracy benchmark. |

## Findings and review

| Term | Meaning |
| --- | --- |
| **Finding** | One potential issue: type, severity (High / Medium / Low / Review), title, detail, and three evidence pointers (OSL location + text, config JSON path + value, report name + sheet + cell). |
| **Review** (severity) | A finding kept for a human look: low-confidence extraction (< 0.7) or a verify-stage disagreement. |
| **Review status** | The user's decision on a finding: OK / Not OK with a comment; also confirmed / false positive / accepted risk for accuracy tracking. |
| **Traceability matrix** | The main review view: one row per requirement, three columns (OSL, config, reports), status match / mismatch / partial / missing / extra. |
| **Re-check** | Re-running stages 5–7 after a rule or trace edit. Seconds, no LLM. |
| **Finalize / final report** | Generating the frozen one-page HTML report after review. Stored once, never regenerated; PDF rendered from it. |

## Configurable checks (admin-ui)

| Term | Meaning |
| --- | --- |
| **Report template** | A sample Excel uploaded for one report type; documents where values live. |
| **Named value** | A pointer into a report: report type, sheet, and a cell (`H9`) or a **label lookup** (the row where column A says "Billing count"). Label lookup preferred. |
| **Check** (expression) | An expression over named values (`billing_count <= delivered_count`) with severity, message, and reasoning. Runs in code at no token cost. Versioned; can be disabled; scoped to all customers or one. |
| **Judgment check** | A check a formula cannot express: an instruction + examples; the LLM sees only the named values and returns pass / fail / review. Use sparingly. |
| **Masked columns** | The admin-maintained list of sensitive columns masked at parse time. |

## Runs and operations

| Term | Meaning |
| --- | --- |
| **Run** | One submission: customer name, order number, configuration ID (informational; duplicates allowed), credit date, programme, notes, files. Each run has its own id. Status `queued` → `running` → `needs_review` → `finalized`, or `failed`. |
| **Credit date** | The as-of date of the credit data in a delivery, entered on the run. Code looks for it in the OSL, the configuration, and the reports and raises `credit_date_missing` when the reports do not carry it (ADR-027). |
| **Input fingerprint** | Hash of all input files + active check versions. A match shows the existing report; re-running needs a logged **rerun reason**. |
| **Stage** | One of the nine pipeline steps; each writes status, duration, and token use to `run_stages` so a failed run resumes. |
| **Stage cache / LLM cache** | `llm_cache`: results keyed by content hash + model + prompt version, so identical content is never sent twice. |
| **Prompt version** | A constant per prompt template, part of the cache key. |
| **Config history** | Captured configs by configuration ID and version (`configs`), copyable into a new run. |
| **Retention** | Runs, files, and stats are deleted after 90 days (`runs.expires_at`); aggregated usage stats are kept. |
| **Shared volume** | The one Docker volume, mounted into api and worker, that holds uploads, reports, and PDFs. |

## Training vocabulary (Phase 6.1, specified but not built)

These terms appear in [`phase-6.1.md`](phase-6.1.md) and ADR-021. Nothing in the code
uses them yet.

| Term | Meaning |
| --- | --- |
| **Train AI mode** | An operator switch. When off the user-ui is exactly what it is today; when on, reviewers can record **observations**. |
| **Observation** | One thing a person knows, in their own words, anchored to what they mean. The raw material of a learned rule; it never runs. |
| **Anchor** | The typed selection an observation points at: a report cell or label, an OSL section, or a config JSON path. What makes synthesis reliable rather than a guess. |
| **Candidate rule** | A rule the model drafted from one or more observations, validated by code and waiting for an administrator. It never runs. |
| **Shadow** | A rule state: it runs on every run and its findings are counted but shown to nobody, so its precision can be measured before it interrupts a reviewer. |
| **Replay** | Running a candidate rule against the golden set and recent finalized runs to see what it would have changed, before approving it. |
| **Dismissal rate** | The share of a rule's findings that reviewers marked OK. The measure of whether a rule is earning its place. |
| **Part** | One of several files uploaded for the same report type in one run, with a label. A check declares whether it evaluates `each` part or the `total`. |
| **Disabled** | A rule an administrator switched off. Reversible at any time, and where a noisy rule goes rather than being deleted. |
| **Soft delete** | A deleted rule stops running and leaves the default view, and can be restored whole for six months. After that the deletion is permanent. |
| **Tombstone** | What survives a permanent deletion: identity, version, provenance, and reasoning, so findings on old runs that cite the rule still explain themselves. |
| **Configuration note** | A standing note on an ETL configuration id, written by anyone. Guidance for every future run of that configuration and an observation in the admin queue at once; never a rule on its own (ADR-024). |
| **Programme rule** | A sentence true of every delivery in a programme, with a strictness (must, should, advisory). The model reads for breaches; code sets the severity from the strictness (ADR-026). |
| **Programme check** | A grep of the OSL, configuration, and report headers for the declared programme's keywords. A mismatch is a finding, never a block. |
| **Field constraint** | A rule about one attribute — never blank, allowed values, a range, a format — stored as structured data and evaluated by code, though it was written in plain words. |

## Identity vocabulary (Phase 6.2, specified but not built)

From [`phase-6.2.md`](phase-6.2.md) and ADR-022. Login ships off; nothing in the code
uses these yet.

| Term | Meaning |
| --- | --- |
| **Placeholder user** | The seeded account every action is attributed to while login is off (John Doe, jdoe@jdoe.com). It cannot be signed in as or deleted, so "placeholder" always reads as "no login was enabled". |
| **Auth switch** | `GREENLIGHT_AI_ADMIN_AUTH` and `GREENLIGHT_AI_USER_AUTH`, independent and both false by default. Off means no prompt, no cookie, today's behaviour. |
| **Bootstrap admin** | The `admin` account created on first startup with admin auth on. Must change its password before it can do anything else. |
| **Attribution** | The actor recorded on a run, a finding decision, a config capture, an observation, and an approval. Always present, because there is always a current user. |
