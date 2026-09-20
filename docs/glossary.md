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
| **Review status** | The reviewer's decision on a finding, one of three: **false positive** (not a real problem), **accepted risk** (real, accepted anyway, always with a comment), or **confirmed** — shown as **Not OK**, meaning the delivery has to change. Undecided until they choose. |
| **Traceability matrix** | The main review view: one row per requirement, three columns (OSL, config, reports), status match / mismatch / partial / missing / extra. |
| **Re-check** | Re-running stages 5–7 after a rule or trace edit. Seconds, no LLM. |
| **Finalize / final report** | Generating the frozen one-page HTML report after review. Stored once, never regenerated; PDF rendered from it. |

## Configurable checks (admin-ui)

| Term | Meaning |
| --- | --- |
| **Report template** | A sample Excel uploaded for one report type; documents where values live. |
| **Named value** | A pointer into a report: report type, sheet, and a cell (`H9`) or a **label lookup** (the row where column A says "Billing count"). Label lookup preferred. |
| **Check** (expression) | An expression over named values (`billing_count <= delivered_count`) with severity, message, and reasoning. Runs in code at no token cost. Versioned; can be disabled; carries a **scope**. |
| **Judgment check** | A check a formula cannot express: an instruction + examples; the LLM sees only the named values and returns pass / fail / review. Use sparingly. |
| **Masked columns** | The admin-maintained list of sensitive columns masked at parse time. |
| **Scope** | Where a definition applies, as one token: `everywhere`, `programme:CODE`, `customer:NAME` or `config:ID`. One module reads it (`greenlight_ai/scopes.py`); the older forms `all` and a bare customer name still parse and are never rewritten (ADR-037). |

### Coverage and lenses (Phase 6.11)

| Term | Meaning |
| --- | --- |
| **Coverage** | What a run actually checked: one state per requirement — **checked** (a report check compared it), **traced but unchecked** (it reached the configuration and no report evidenced it), **untraced** (nothing implements it), **verified by hand** (free text, or a check that could not be evaluated) — plus how many checks touched each uploaded report. Code, no model (ADR-035). |
| **Acknowledgement** | A person's record that they saw a coverage gap before the report was frozen. Not a decision that the delivery is fine; the gate wants one for every unevidenced requirement and every check that could not be evaluated. |
| **Attestation** | What a reviewer confirms when they freeze a report: the coverage counts, the gaps acknowledged, the shadow rules and definition versions in force, and the run's notices. Stored on the report and rendered in it. |
| **Second approver** | A programme's optional rule that someone other than the reviewer signs off findings the reviewer waved through that the programme treats as serious. Off by default, and inert while login is off, because both people would be the same placeholder account (ADR-036). |
| **Notice** | Something a run must tell the reviewer that is not a finding: a second opinion that could not be obtained, a programme reading that did not run, a call cap reached. |
| **Lens** | One of stage 8's readers — delivery, compliance, requirements owner — each given the same finding and evidence and none given another's answer. Code merges them. A lens changes confidence, never severity (ADR-034). |
| **Critique pass** | One call that reads a drafted rule back against the statements it came from, allowing at most one redraft. Authoring time, once per candidate (Phase 6.11g). |

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
| **Origin** (of a finding) | Where it came from: `built_in` when code produced it from the OSL and the configuration alone, else the origin of the rule behind it — `admin`, `guide`, `meaning` or `learned`. Shown on the review screen and in the evidence drawer (Phase 6.13b). |
| **Outcome** (of an observation) | What became of it, read from the rule tables each time: waiting · drafted · approved (the rule is in shadow) · live · disabled · rejected. Never stored, so never stale. |
| **Front door** | One box in the admin console where an administrator writes what they want checked. The model places the sentence on an existing surface; the drafting, the validation and the approval are the training loop's, unchanged. It adds no surface and no evaluator (ADR-037). |
| **Surface** | One of the places an administrator can tell the tool something: an artifact type's AI context, a validation guide, a meaning entry, a named value, a check, a compliance rule, a programme rule, a standing instruction, a configuration note, a field constraint, an alias, a masked column, a reverse-pass category. |
| **Shadow** | A rule state: it runs on every run and its findings are counted but shown to nobody, so its precision can be measured before it interrupts a reviewer. |
| **Replay** | Running a candidate rule against the golden set and recent finalized runs to see what it would have changed, before approving it. |
| **Dismissal rate** | The share of a rule's findings that reviewers marked OK. The measure of whether a rule is earning its place. |
| **Part** | One of several files uploaded for the same report type in one run, with a label. A check declares whether it evaluates `each` part or the `total`. |
| **Disabled** | A rule an administrator switched off. Reversible at any time, and where a noisy rule goes rather than being deleted. |
| **Soft delete** | A deleted rule stops running and leaves the default view, and can be restored whole for six months. After that the deletion is permanent. |
| **Tombstone** | What survives a permanent deletion: identity, version, provenance, and reasoning, so findings on old runs that cite the rule still explain themselves. |
| **Configuration note** | A standing note on an ETL configuration id, written by anyone. Guidance for every future run of that configuration and an observation in the admin queue at once; never a rule on its own (ADR-024). |
| **Validation guide** | Per report type: what a cell means and where it answers to in the OSL and the configuration, with examples from the samples. The model reads it as background; a concrete entry compiles into a shadow check (ADR-029). |
| **Delivery drift** | What changed since the previous finalized run of the same configuration: new, resolved and carried-over Not OK findings, requirements whose value changed, and the configuration diff by path. Computed in code (ADR-030). |
| **Theme** | One of four named palettes, each with a light and a dark variant. The deployment's default and lock come from the console over `.env`; a person's own choice, where allowed, wins for their browser (ADR-031). |
| **Meaning entry** | One OSL requirement's links: the configuration path that implements it and the report cells that evidence it, global or per programme. Proposed by the mapping interview, confirmed by an administrator, compiled by code into a shadow check (ADR-033). |
| **Mapping interview** | One cached model call per OSL section over the samples in scope, proposing meaning entries and asking a question when a requirement cannot be placed. |
| **Definition version** | A snapshot of an artifact type (fields, samples, guide) or a programme's rule set, taken after every save. Ten are listed; a revert restores one as a new version (ADR-029). |
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
