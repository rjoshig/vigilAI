# LLM usage and privacy rules

Governs every LLM call and every place customer data could leak. Source:
[`design.md`](design.md) "Security and PII", "LLM adapter", "LLM cost controls"; ADR-001,
ADR-003, ADR-004, ADR-005.

## What the LLM may see

| Allowed in a prompt | Never in a prompt |
| --- | --- |
| OSL text (headings, sentences, criteria tables) | Sample rows from the DIRT sample tab, masked or not |
| Config JSON blocks and their JSON paths | Any cell value from a report that is not an aggregate (min, max, mean, count, null count, distinct keys) |
| Canonical rules, trace pairs, findings (field names, thresholds, aggregate stats) | Customer identifiers beyond what the OSL itself contains |
| A lens's finding and evidence; the list of requirements no report evidenced, as text and references; a drafted rule with the statements it came from | Any report value or configuration value not already in a finding's evidence |
| Named values and the reasoning behind an admin check | Uploaded file contents verbatim |
| An administrator's worked examples: what a stage would be shown and a good answer, checked by the tripwire on save (ADR-038) | A report row or a configuration value pasted into an example |
| Configuration paths and the *shape* of their contents, when the model is asked where a compliance control is implemented (ADR-036 shape, Phase 6.15) | Any value at those paths — the locator is shown `suppressions.ofac (boolean)`, never `true` |
| A capped extract of the delivery's own words — OSL prose, configuration paths and descriptions, report sheet names and column headers — when the model is asked which programme it reads like (ADR-045) | Any data row. Headers say what a delivery is about; rows say who is in it |

The model never needs sample rows to do its job. If a stage seems to need one, that is a
`# SPEC GAP:` and a question, not a prompt change.

## Where PII may exist

| Place | PII allowed? |
| --- | --- |
| Uploaded files on the shared volume | Yes, unmasked (the only place) |
| Postgres `findings.evidence`, `rules`, `traces`, report sample references | Masked values only; the masked-column list is admin-maintained |
| Prompts, `llm_cache`, `llm_calls` | No |
| Application logs | No — ids and counts only. `LLM_LOG_PROMPTS=true` is for synthetic data on a developer machine only |
| `tests/fixtures/`, the repo, commit messages, PR text | No — fixtures are synthetic (invented customers, states, thresholds) |
| The review screen, the HTML report, the PDF | Masked values only; no unmask control in v1 |

### The two prompts that run only where code failed

Both are narrow by construction and are listed here because each sends something the
other prompts do not.

**The compliance locator** (stage 6) is shown configuration paths and the type of what
sits at each — never a value. It answers *where is this control, if anywhere*, and code
checks the path it quotes was one of the paths offered.

**The programme reading** (stage 7) is shown a capped extract of the delivery's own
words, and is the one prompt whose input is largely free prose the tool did not compose.
Three things bound it: the extract is built from the same haystack the keyword check
greps — OSL text, configuration paths and descriptions, report sheet names and headers,
and **never a data row**; the prompt instructs the model not to quote a phrase
containing a person's name, address or account number, because what it quotes is shown
to an administrator and offered as a keyword; and the tripwire scans the assembled
prompt like every other, failing closed (ADR-018).

Neither call happens on a delivery the deterministic check already answered, so neither
is on the common path.

## The adapter contract (ADR-004)

- Only `src/greenlight_ai/llm/` makes network calls to a model. Everything else calls
  `LLMClient.complete(system, user, schema)` and gets an `LLMResult` (text, parsed JSON,
  token counts, latency).
- Provider (`openai` | `anthropic` | `mock`), base URL, model, max tokens, temperature 0,
  timeout, and concurrency come from `.env`. No vendor SDKs; plain `httpx`.
- One prompt = one narrow task with small input and small output: one OSL section or table,
  one config block, one (requirement, element) pair, one finding to verify.
- JSON-only output validated by a Pydantic schema; on failure, one retry with the
  validation error appended. Guided / JSON-schema decoding is turned on when the serving
  stack supports it.

## The cache contract (ADR-005)

- Key = `sha256(canonical content) + model name + prompt version`. Changing the model or a
  prompt refreshes results; nothing else does.
- Checked **before every call**; a miss is the only path to the network. Hits increment
  `llm_cache.hits`.
- Entries hold no sample rows and expire with the 90-day retention.
- Per-run budget `LLM_MAX_TOKENS_PER_RUN`: exceeding it stops the run and flags it.

## Never-twice rules

- The same content is never sent to the LLM twice (the cache).
- A finalized report is never regenerated; PDF is rendered from the stored HTML.
- Re-running identical inputs (same fingerprint) requires a `rerun_reason`, which is logged
  on the run and in `audit_log`.
- Review decisions, comments, re-check, report view, and download never call the LLM.

## Fixture policy (ADR-003)

- `tests/fixtures/` is generated by `scripts/` from a spec of invented values. No fixture
  is derived from, or resembles, a real customer's file.
- The golden set (10–20 synthetic OSLs with known-correct rules) is the accuracy benchmark
  for extraction and runs whenever a prompt or the model changes.
- Real files are used only in-house, in Phase 6, on a machine that never pushes them.
  `.gitignore` blocks `*.docx` / `*.xlsx` outside `tests/fixtures/` as a backstop.

## Open items for the security / compliance team (from the design doc)

- Is 90-day storage of DIRT files containing PII approved, or should that file type expire
  sooner?
- Encrypted Docker volumes and TLS at the reverse proxy are the deployment assumption;
  confirm the in-house standard.


## Worked examples (ADR-038)

An administrator can add worked examples to six prompt stages. They are the second place
text an administrator writes reaches a prompt, and they are handled like the first.

- **The tripwire runs on save**, not when the prompt is assembled. An example is text
  pasted from a real delivery, and save is the last moment the person who pasted it can
  take it out.
- **An example is a pair, not a sentence.** What the model would be shown and a good
  answer, with no free-text field reaching a prompt. The note saying why the example is
  there is for the next administrator and is never rendered.
- **The answer is schema-constrained before storage.** The stage's own Pydantic model
  validates it, so nothing teaches a shape the pipeline cannot parse.
- **They are shown as examples.** The block is rendered after the built-in examples under
  a line saying they show the shape of a good answer and are not rules, and nothing in
  the library can make anything run: rules live in the rule tables and code evaluates
  them (ADR-001).
- **They are part of the cache key by being part of the prompt.** Adding one refreshes
  exactly the calls it changes.

## Training synthesis (ADR-021)

Train AI mode adds one more place text reaches the model: the sentences reviewers
write about what a delivery should contain. It is the riskiest prompt in the tool,
because its output becomes a rule applied to every run, and it is handled accordingly.

- **The tripwire runs when an observation is saved**, not only when the prompt is
  assembled. A reviewer typing while looking at real data is exactly where an account
  number gets pasted, and the moment they press save is the only point at which the
  person who pasted it can still take it out.
- **The statements are delimited and labelled as data.** They reach the prompt between
  `<statements>` markers, with an instruction that everything inside is a person's
  description to interpret and never an instruction to follow. A statement that asks
  the model to do something else comes back as unsupported.
- **The answer is schema-constrained.** Nothing downstream parses prose. Loose parsing
  of free-form model output is where code starts trusting something nobody checked,
  and that is the actual injection exposure rather than the text itself.
- **Nothing runs until a person approves it**, and code has rejected everything
  malformed by then. That is the real control; the first three are what make it hard
  to reach.
- **No report values are sent.** The model sees the sentence, what the person pointed
  at, and the list of attribute names the tool knows. It never sees a cell's contents.

The **front door** (Phase 6.12b) adds one call in front of this, `admin_classify`, and
no new exposure. It sends the administrator's sentence and the names of the attributes
and report types the tool knows, inside a `<statement>` block labelled as data, and gets
back one word from a closed set with a reason and a confidence. It writes nothing: the
drafting, the validation and the approval are the ones above, so the same tripwire runs
on the same text at the same moment and the same person still approves whatever runs. A
sentence the model will not place creates nothing at all.
