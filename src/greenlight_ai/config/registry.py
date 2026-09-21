"""The catalogue of settings an administrator may change (ADR-023).

Everything the console can show or edit is declared here once: its type, its default,
the environment variable it falls back to, and whether it may be changed at runtime at
all. Nothing else in the code decides those things, so the console and the environment
can never disagree about what a setting is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Literal, Sequence

__all__ = ["SettingSpec", "SETTINGS", "SETTINGS_BY_KEY", "GROUPS", "group_of"]

Kind = Literal["bool", "int", "str", "secret", "enum"]


@dataclass(frozen=True)
class SettingSpec:
    """One setting the console knows about.

    Attributes:
        key: The stable identifier, also the row key in ``app_settings``.
        env: The environment variable it falls back to.
        label: What the console calls it.
        group: Which section of the console it appears in.
        kind: How it is typed and rendered.
        default: The built-in value, used when neither layer supplies one.
        help: One sentence on what it does and what changing it costs.
        editable: Whether it may be changed at runtime. A false value is shown
            read-only, because changing it from the console could make the console
            unreachable.
        choices: The allowed values for an ``enum``.
        minimum: The lowest accepted value for an ``int``.
        maximum: The highest accepted value for an ``int``.
        restart: Whether a change needs a restart to take effect. Everything editable
            here takes effect on the next request or the next job, so this is false
            throughout; the field exists so that stays a deliberate claim.
    """

    key: str
    env: str
    label: str
    group: str
    kind: Kind
    default: object
    help: str
    editable: bool = True
    choices: Sequence[str] = field(default_factory=tuple)
    minimum: int | None = None
    maximum: int | None = None
    restart: bool = False


#: The sections the console draws, in order.
GROUPS: Final[tuple[str, ...]] = (
    "Model",
    # Every row in it qualifies something in "Model", so it sits directly after.
    "Chat",
    "Anomalies",
    "Training",
    "Login",
    "Throughput",
    "Availability",
    "Uploads",
    "Retention",
    "Appearance",
    "Platform",
)

SETTINGS: Final[tuple[SettingSpec, ...]] = (
    # --- the model ------------------------------------------------------------------
    SettingSpec(
        key="llm.provider",
        env="LLM_PROVIDER",
        label="Provider",
        group="Model",
        kind="enum",
        default="mock",
        choices=("mock", "openai", "anthropic"),
        help="Which adapter to use. `mock` never leaves the machine and is what tests "
        "run on. The wire format is the only difference; there is no vendor SDK.",
    ),
    SettingSpec(
        key="llm.base_url",
        env="LLM_BASE_URL",
        label="Base URL",
        group="Model",
        kind="str",
        default="http://localhost:11434/v1",
        help="Where the provider lives. For a local model this is the OpenAI-compatible "
        "endpoint the serving stack exposes.",
    ),
    SettingSpec(
        key="llm.model",
        env="LLM_MODEL",
        label="Model",
        group="Model",
        kind="str",
        default="gemma3:27b",
        help="The model name the provider expects. It is part of every cache key, so "
        "changing it means the next run re-asks everything.",
    ),
    SettingSpec(
        key="llm.api_key",
        env="LLM_API_KEY",
        label="API key",
        group="Model",
        kind="secret",
        default="",
        help="Stored encrypted and never shown again. Needs GREENLIGHT_AI_SECRET_KEY to be "
        "set in the environment; without it the key stays in .env instead.",
    ),
    SettingSpec(
        key="llm.max_tokens",
        env="LLM_MAX_TOKENS",
        label="Max tokens per call",
        group="Model",
        kind="int",
        default=2000,
        minimum=256,
        maximum=32000,
        help="The ceiling on one response. Too low truncates an extraction; too high "
        "only costs money.",
    ),
    SettingSpec(
        key="llm.temperature_pct",
        env="LLM_TEMPERATURE_PCT",
        label="Temperature (%)",
        group="Model",
        kind="int",
        default=0,
        minimum=0,
        maximum=100,
        help="Kept at zero: the same inputs must produce the same findings, and the "
        "cache assumes it.",
    ),
    SettingSpec(
        key="llm.timeout_s",
        env="LLM_TIMEOUT_S",
        label="Timeout (seconds)",
        group="Model",
        kind="int",
        default=120,
        minimum=5,
        maximum=900,
        help="How long one call may take before the stage fails and retries.",
    ),
    SettingSpec(
        key="llm.max_concurrency",
        env="LLM_MAX_CONCURRENCY",
        label="Calls in flight per worker",
        group="Model",
        kind="int",
        default=4,
        minimum=1,
        maximum=64,
        help="Raising it finishes a run sooner and puts more load on the model "
        "endpoint at once.",
    ),
    SettingSpec(
        key="llm.max_tokens_per_run",
        env="LLM_MAX_TOKENS_PER_RUN",
        label="Token budget per run",
        group="Model",
        kind="int",
        default=400000,
        minimum=10000,
        maximum=10000000,
        help="A run that exceeds it stops and is flagged, so one pathological input "
        "cannot spend a day's budget.",
    ),
    SettingSpec(
        key="llm.verify_lenses",
        env="LLM_VERIFY_LENSES",
        label="Second-opinion lenses",
        group="Model",
        kind="str",
        default="single",
        help="Which readers check a high-severity finding at stage 8: 'single', or a "
        "comma-separated list of delivery, compliance, requirements. Each is one call per "
        "finding; code merges what they say and none can raise a severity (ADR-034).",
    ),
    SettingSpec(
        key="llm.max_lens_calls_per_run",
        env="LLM_MAX_LENS_CALLS_PER_RUN",
        label="Lens calls per run",
        group="Model",
        kind="int",
        default=150,
        minimum=0,
        maximum=10000,
        help="A ceiling on stage-8 lens calls beside the token budget. Past it, the "
        "remaining findings are left unverified and the run says so.",
    ),
    SettingSpec(
        key="llm.max_attribute_calls_per_run",
        env="LLM_MAX_ATTRIBUTE_CALLS_PER_RUN",
        label="Attribute lookups per run",
        group="Model",
        kind="int",
        default=20,
        minimum=0,
        maximum=1000,
        help="How many times a run may ask the model which column an attribute is, "
        "when four deterministic rungs and the dictionary could not say. A soft "
        "limit: past it the run stops asking and names what it did not look for, and "
        "nothing is refused. Every answer a person accepts becomes a dictionary "
        "spelling, so this number should fall to zero as the dictionary fills. Zero "
        "means never ask, and the tool reports the names it could not resolve.",
    ),
    SettingSpec(
        key="llm.guided_json",
        env="LLM_GUIDED_JSON",
        label="Ask the endpoint for JSON",
        group="Model",
        kind="enum",
        default="auto",
        choices=("off", "auto", "on"),
        help="Whether to send the answer's schema with the request, so a serving stack "
        "that supports guided decoding (vLLM does) cannot return anything that is not "
        "that shape. `auto` sends it and, if the endpoint refuses the request, retries "
        "once without it and stops trying until the next restart — so a gateway that "
        "has never heard of it is not a broken deployment. `on` never stops trying; "
        "`off` is the behaviour before this setting existed.",
    ),
    SettingSpec(
        key="llm.pii_tripwire",
        env="LLM_PII_TRIPWIRE",
        label="PII tripwire",
        group="Model",
        kind="bool",
        default=True,
        help="Scans every assembled prompt and refuses to send a match. Leave it on; "
        "a prompt already sent cannot be recalled.",
    ),
    SettingSpec(
        key="llm.log_prompts",
        env="LLM_LOG_PROMPTS",
        label="Log prompts",
        group="Model",
        kind="bool",
        default=False,
        help="Writes full prompts to the log. For debugging on synthetic data only; "
        "logs hold ids and counts otherwise.",
    ),
    # --- training -------------------------------------------------------------------
    # --- anomalies (Phase 6.21c) ------------------------------------------------------
    SettingSpec(
        key="anomaly.enabled",
        env="GREENLIGHT_AI_ANOMALY",
        label="Compare a delivery with its own history",
        group="Anomalies",
        kind="bool",
        default=True,
        help="Raise a low-severity finding when an attribute's null rate, range or "
        "mean is unlike the previous finalized deliveries of the same configuration. "
        "The only finding the tool makes that no rule covers. Costs no model call, and "
        "says nothing until there is enough history.",
    ),
    SettingSpec(
        key="anomaly.min_history",
        env="GREENLIGHT_AI_ANOMALY_MIN_HISTORY",
        label="Deliveries before it speaks",
        group="Anomalies",
        kind="int",
        default=3,
        minimum=2,
        maximum=50,
        help="How many previous finalized deliveries of a configuration are needed "
        "before anything is compared. A baseline of one delivery is not a baseline.",
    ),
    SettingSpec(
        key="anomaly.sensitivity_pct",
        env="GREENLIGHT_AI_ANOMALY_SENSITIVITY_PCT",
        label="How far is far",
        group="Anomalies",
        kind="int",
        default=400,
        minimum=100,
        maximum=1000,
        help="How far from the usual figure counts, as a percentage of how much this "
        "configuration's deliveries normally vary. 400 means four times the usual "
        "spread. Lower finds more and is wrong more often.",
    ),
    SettingSpec(
        key="anomaly.model_reads_shape",
        env="GREENLIGHT_AI_ANOMALY_MODEL",
        label="Let the AI read the shape too",
        group="Anomalies",
        kind="bool",
        default=False,
        help="One extra model call per run. It is shown the aggregate statistics and "
        "nothing else — never a row — and asked what looks unusual; code decides the "
        "severity and it is always a question rather than a failure. Off by default "
        "because it spends tokens on every run, including the ones with nothing wrong.",
    ),
    SettingSpec(
        key="training.enabled",
        env="GREENLIGHT_AI_TRAIN_AI_MODE",
        label="Train AI mode",
        group="Training",
        kind="bool",
        default=False,
        help="Lets reviewers record what they know, anchored to the cell or clause "
        "they mean. Observations never run; an administrator synthesizes and approves "
        "them first.",
    ),
    SettingSpec(
        key="training.shadow_default",
        env="GREENLIGHT_AI_TRAINING_SHADOW_DEFAULT",
        label="Approve into shadow",
        group="Training",
        kind="bool",
        default=True,
        help="An approved rule runs silently until an administrator activates it. "
        "Switching this off sends approvals straight to active, which spends reviewer "
        "trust on a rule whose precision nobody has seen yet.",
    ),
    SettingSpec(
        key="training.replay_runs",
        env="GREENLIGHT_AI_TRAINING_REPLAY_RUNS",
        label="Recent runs used in a replay",
        group="Training",
        kind="int",
        default=25,
        minimum=0,
        maximum=500,
        help="How many recent finalized runs a candidate rule is evaluated against "
        "before approval. Their stored reports are parsed again and the rule is run "
        "over them; zero skips the replay entirely.",
    ),
    # --- login ----------------------------------------------------------------------
    SettingSpec(
        key="auth.admin",
        env="GREENLIGHT_AI_ADMIN_AUTH",
        label="Require sign-in for the admin console",
        group="Login",
        kind="bool",
        default=False,
        help="Turning this off from the console is refused while you are signed in, "
        "because it would leave the console open to anyone who can reach it.",
    ),
    SettingSpec(
        key="auth.user",
        env="GREENLIGHT_AI_USER_AUTH",
        label="Require sign-in for the user app",
        group="Login",
        kind="bool",
        default=False,
        help="With it off, every action is attributed to the placeholder account.",
    ),
    SettingSpec(
        key="auth.session_ttl_s",
        env="GREENLIGHT_AI_SESSION_TTL_S",
        label="Session lifetime (seconds)",
        group="Login",
        kind="int",
        default=8 * 60 * 60,
        minimum=300,
        maximum=30 * 24 * 60 * 60,
        help="How long a sign-in lasts regardless of activity. The default is a " "working day.",
    ),
    SettingSpec(
        key="auth.idle_ttl_s",
        env="GREENLIGHT_AI_SESSION_IDLE_S",
        label="Idle timeout (seconds)",
        group="Login",
        kind="int",
        default=60 * 60,
        minimum=60,
        maximum=7 * 24 * 60 * 60,
        help="How long a session may go unused. This is what protects an unattended " "screen.",
    ),
    SettingSpec(
        key="auth.min_password_length",
        env="GREENLIGHT_AI_MIN_PASSWORD_LENGTH",
        label="Minimum password length",
        group="Login",
        kind="int",
        default=12,
        minimum=8,
        maximum=128,
        help="The only composition rule there is. Complexity classes and forced expiry "
        "push people toward predictable passwords.",
    ),
    SettingSpec(
        key="auth.lockout_threshold",
        env="GREENLIGHT_AI_LOCKOUT_THRESHOLD",
        label="Failures before lockout",
        group="Login",
        kind="int",
        default=5,
        minimum=3,
        maximum=50,
        help="Consecutive failed sign-ins before the account is locked.",
    ),
    SettingSpec(
        key="auth.lockout_s",
        env="GREENLIGHT_AI_LOCKOUT_S",
        label="Lockout duration (seconds)",
        group="Login",
        kind="int",
        default=15 * 60,
        minimum=30,
        maximum=24 * 60 * 60,
        help="How long the lock lasts before it clears itself.",
    ),
    # --- throughput -------------------------------------------------------------
    SettingSpec(
        key="queue.max_concurrent_runs",
        env="GREENLIGHT_AI_MAX_CONCURRENT_RUNS",
        label="Runs processing at once",
        group="Throughput",
        kind="int",
        default=4,
        minimum=1,
        maximum=64,
        help="How many runs may be in flight across all workers. Everything else "
        "waits in the queue, and the user app shows its position.",
    ),
    SettingSpec(
        key="queue.starts_per_window",
        env="GREENLIGHT_AI_STARTS_PER_WINDOW",
        label="Runs started per window",
        group="Throughput",
        kind="int",
        default=20,
        minimum=1,
        maximum=1000,
        help="A rate limit on starting work, so a bulk submission cannot empty the "
        "token budget in a minute.",
    ),
    SettingSpec(
        key="queue.window_s",
        env="GREENLIGHT_AI_RATE_WINDOW_S",
        label="Window length (seconds)",
        group="Throughput",
        kind="int",
        default=300,
        minimum=30,
        maximum=24 * 60 * 60,
        help="The period the start limit is counted over. Five minutes by default.",
    ),
    SettingSpec(
        key="queue.max_queue_wait_s",
        env="GREENLIGHT_AI_MAX_QUEUE_WAIT_S",
        label="Longest acceptable queue wait (seconds)",
        group="Throughput",
        kind="int",
        default=30 * 60,
        minimum=60,
        maximum=7 * 24 * 60 * 60,
        help="A run waiting longer than this is flagged on the dashboard. It does not "
        "cancel anything; it is the number that says the queue is too long.",
    ),
    SettingSpec(
        key="queue.per_order_limit",
        env="GREENLIGHT_AI_PER_ORDER_LIMIT",
        label="Queued runs per order number",
        group="Throughput",
        kind="int",
        default=3,
        minimum=1,
        maximum=100,
        help="Stops one order number filling the queue by resubmission.",
    ),
    # --- uploads ------------------------------------------------------------------
    SettingSpec(
        key="uploads.max_mb",
        env="GREENLIGHT_AI_MAX_UPLOAD_MB",
        label="Maximum upload size (MB)",
        group="Uploads",
        kind="int",
        default=50,
        minimum=1,
        maximum=2000,
        help="Enforced while streaming, so an oversized file is refused before it "
        "lands on disk.",
    ),
    # --- the report chat (Phase 8f) ---------------------------------------------------
    # Nine rows, and the console needs no code for any of them: it renders the group,
    # ADR-023 resolves each value, and the `help` line is the only account an
    # administrator gets of a value they cannot otherwise observe.
    SettingSpec(
        key="chat.enabled",
        env="GREENLIGHT_AI_CHAT",
        label="Report chat",
        group="Chat",
        kind="bool",
        default=False,
        help="Ask questions about a frozen report, in a panel on the report page. Off "
        "means no launcher and an endpoint that refuses, so a deployment that upgrades "
        "never silently gains an outbound model surface. It reads one run and changes "
        "nothing.",
    ),
    SettingSpec(
        key="chat.model",
        env="GREENLIGHT_AI_CHAT_MODEL",
        label="Model",
        group="Chat",
        kind="str",
        default="",
        help="Which model answers. Empty follows the Model section above, so nothing "
        "changes on upgrade. A cheaper model here never touches validation accuracy, "
        "and because the model name is part of every cache key the two can never serve "
        "each other's answers.",
    ),
    SettingSpec(
        key="chat.max_tokens",
        env="GREENLIGHT_AI_CHAT_MAX_TOKENS",
        label="Maximum tokens per answer",
        group="Chat",
        kind="int",
        default=800,
        minimum=256,
        maximum=4000,
        help="The ceiling on one answer. Too low truncates mid-sentence, which on a "
        "streamed answer is visible and alarming; too high only costs money.",
    ),
    SettingSpec(
        key="chat.temperature_pct",
        env="GREENLIGHT_AI_CHAT_TEMPERATURE_PCT",
        label="Temperature (%)",
        group="Chat",
        kind="int",
        default=0,
        minimum=0,
        maximum=100,
        help="Zero repeats itself exactly and caches well. Raising it reads more "
        "naturally and makes the same question answerable two ways, which on a QC "
        "report is a worse trade than it looks. It is part of the cache key, so raising "
        "it re-asks everything.",
    ),
    SettingSpec(
        key="chat.max_questions_per_run",
        env="GREENLIGHT_AI_CHAT_MAX_PER_RUN",
        label="Questions per run",
        group="Chat",
        kind="int",
        default=20,
        minimum=1,
        maximum=200,
        help="How long one conversation may go. Reached, the panel says so rather than " "failing.",
    ),
    SettingSpec(
        key="chat.max_questions_per_day",
        env="GREENLIGHT_AI_CHAT_MAX_PER_DAY",
        label="Questions per person per day",
        group="Chat",
        kind="int",
        default=50,
        minimum=0,
        maximum=500,
        help="The per-person ceiling, and the lever for a staged rollout: set it to "
        "zero to deny the feature to everybody until you are ready.",
    ),
    SettingSpec(
        key="chat.max_turns",
        env="GREENLIGHT_AI_CHAT_MAX_TURNS",
        label="Transcript turns kept",
        group="Chat",
        kind="int",
        default=8,
        minimum=1,
        maximum=30,
        help="How much history is re-sent with each question, and the main cost lever: "
        "every turn re-sends the ones before it. Lower it and the chat forgets sooner; "
        "raise it and each answer costs more than the last.",
    ),
    SettingSpec(
        key="chat.timeout_s",
        env="GREENLIGHT_AI_CHAT_TIMEOUT_S",
        label="Timeout (seconds)",
        group="Chat",
        kind="int",
        default=60,
        minimum=10,
        maximum=300,
        help="How long an answer may take before it is abandoned. An abandoned answer "
        "stores nothing and is never cached.",
    ),
    SettingSpec(
        key="chat.report_aggregates",
        env="GREENLIGHT_AI_CHAT_AGGREGATES",
        label="Include report aggregates",
        group="Chat",
        kind="bool",
        default=False,
        help="CHANGES WHAT LEAVES THE BUILDING. Off, the chat sees only what the "
        "pipeline already derived. On, it also sees per-column figures code computed — "
        "minimum, maximum, mean, count, nulls, distinct — so it can answer what a "
        "field's distribution looks like. Never a row and never a cell that is not an "
        "aggregate; the tripwire still fails closed on every prompt.",
    ),
    # --- retention ------------------------------------------------------------------
    SettingSpec(
        key="retention.days",
        env="GREENLIGHT_AI_RETENTION_DAYS",
        label="Keep runs for (days)",
        group="Retention",
        kind="int",
        default=90,
        minimum=1,
        maximum=3650,
        help="Runs, their files, and their findings are deleted after this. Aggregated "
        "usage survives. A run is stamped with its expiry when it is created, so a "
        "change here applies to runs made from now on and never shortens the life of "
        "one that already exists.",
    ),
    SettingSpec(
        key="retention.draft_days",
        env="GREENLIGHT_AI_DRAFT_DAYS",
        label="Keep unsubmitted drafts for (days)",
        group="Retention",
        kind="int",
        default=5,
        minimum=1,
        maximum=90,
        help="A cloned run nobody submitted is deleted after this, with anything "
        "uploaded to it. The countdown is shown on the draft itself. Like the setting "
        "above, it applies to drafts made from now on; one that already exists keeps "
        "the date it was given.",
    ),
    # --- appearance (Phase 6.6) --------------------------------------------------------
    SettingSpec(
        key="ui.theme",
        env="GREENLIGHT_AI_UI_THEME",
        label="Default theme",
        group="Appearance",
        kind="enum",
        default="classic-teal-navy",
        help="The look every browser starts on, in both apps. A person's own choice, "
        "where allowed, wins for that browser.",
        choices=("classic-teal-navy", "classic-teal", "light-blue-yellow", "default"),
    ),
    # --- availability (Phase 6.14j) ------------------------------------------------
    SettingSpec(
        key="queue.grace_seconds",
        env="GREENLIGHT_AI_QUEUE_GRACE_S",
        label="Seconds to change your mind",
        group="Availability",
        kind="int",
        default=30,
        minimum=0,
        maximum=600,
        help="How long a submitted run waits before the worker may pick it up. During "
        "that window the person who submitted it can cancel, having spent nothing. "
        "Set it to 0 to start runs immediately.",
    ),
    SettingSpec(
        key="queue.paused",
        env="GREENLIGHT_AI_QUEUE_PAUSED",
        label="Hold the queue",
        group="Availability",
        kind="bool",
        default=False,
        help="Submissions are accepted and queue up as usual, and nothing new is "
        "started until you release it. For a model endpoint that is down, or a window "
        "where you would rather nothing ran. Work already running finishes.",
    ),
    SettingSpec(
        key="submissions.paused",
        env="GREENLIGHT_AI_SUBMISSIONS_PAUSED",
        label="Stop accepting submissions",
        group="Availability",
        kind="bool",
        default=False,
        help="New runs are refused with the message below; everything already queued "
        "still runs. Stronger than holding the queue: use it when you do not want work "
        "piling up behind a hold.",
    ),
    SettingSpec(
        key="maintenance.mode",
        env="GREENLIGHT_AI_MAINTENANCE",
        label="Maintenance mode",
        group="Availability",
        kind="bool",
        default=False,
        help="The user app shows a maintenance page instead of itself. This console "
        "keeps working, so you can always switch it back off. It also stops "
        "submissions and holds the queue for as long as it is on.",
    ),
    SettingSpec(
        key="maintenance.message",
        env="GREENLIGHT_AI_MAINTENANCE_MESSAGE",
        label="What to tell people",
        group="Availability",
        kind="str",
        default=(
            "Greenlight AI is briefly unavailable for maintenance. Runs already "
            "submitted are safe and will continue when it returns."
        ),
        help="Shown on the maintenance page and when a submission is refused. Say when "
        "you expect to be back, if you know.",
    ),
    SettingSpec(
        key="cost.per_million_tokens",
        env="GREENLIGHT_AI_COST_PER_MILLION_TOKENS",
        label="Cost per million tokens",
        group="Availability",
        kind="int",
        default=0,
        minimum=0,
        maximum=1_000_000,
        help="What a million tokens costs, in whole currency units, so the token "
        "counts the tool already keeps can be read as money. **Zero, the default, "
        "means the figures stay in tokens and no number is invented** — which is the "
        "right state until somebody who knows the contract fills this in.",
    ),
    SettingSpec(
        key="cost.currency",
        env="GREENLIGHT_AI_COST_CURRENCY",
        label="Currency",
        group="Availability",
        kind="str",
        default="USD",
        help="What the cost figures are denominated in. Shown beside every amount, "
        "because a number with no currency on it is a number somebody will read as "
        "theirs.",
    ),
    SettingSpec(
        key="cost.monthly_warning",
        env="GREENLIGHT_AI_COST_MONTHLY_WARNING",
        label="Warn above, per month",
        group="Availability",
        kind="int",
        default=0,
        minimum=0,
        maximum=100_000_000,
        help="Show a warning on the usage screen once this month's spend passes this "
        "figure. **A warning, never a refusal**: the only hard stop in the product is "
        "the per-run token budget, and adding a second one is a decision for after "
        "somebody has looked at these numbers. Zero switches the band off.",
    ),
    SettingSpec(
        key="value.hours_per_order",
        env="GREENLIGHT_AI_HOURS_PER_ORDER",
        label="Hours a manual check takes",
        group="Availability",
        kind="int",
        default=4,
        minimum=0,
        maximum=40,
        help="Roughly how long one order takes to check by hand, in hours. Used to "
        "report the manual effort the tool has displaced. It is your number, not a "
        "measurement the tool makes — the report says so, and says which number was "
        "used, so a reader can judge it.",
    ),
    SettingSpec(
        key="ui.tagline",
        env="GREENLIGHT_AI_UI_TAGLINE",
        label="Tagline",
        group="Appearance",
        kind="str",
        default="Nothing ships without a green light.",
        help="The line under the mark in both apps' sidebars. Change it to say what "
        "this deployment is for, or clear it to show nothing.",
    ),
    SettingSpec(
        key="ui.tooltips",
        env="GREENLIGHT_AI_UI_TOOLTIPS",
        label="Explain each screen",
        group="Appearance",
        kind="bool",
        default=True,
        help="On by default: each admin screen and its less obvious fields carry a "
        "short note saying what the surface is for, how it is meant to be used, and "
        "what belongs somewhere else. Switch it off once the console is familiar; "
        "nothing else changes, and the markers saying which fields reach the model "
        "stay either way, because those are facts about the run rather than help.",
    ),
    SettingSpec(
        key="ui.guide",
        env="GREENLIGHT_AI_UI_GUIDE",
        label="Show the Guide",
        group="Appearance",
        kind="bool",
        default=True,
        help="On by default: each app carries a Guide in its sidebar, written for the "
        "person using that app, from the same source as their training document. "
        "Switch it off where training is delivered another way and a second copy in "
        "the product would be one more thing to keep current. It changes nothing but "
        "whether the Guide is offered — no check, no rule and no run is affected.",
    ),
    SettingSpec(
        key="ui.setup_markers",
        env="GREENLIGHT_AI_UI_SETUP_MARKERS",
        label="Show setup-only markers",
        group="Appearance",
        kind="bool",
        default=True,
        help="On by default: fields that are used while you set the product up, but "
        "never when a delivery is checked, say so — the sample workbooks and an "
        "artifact type's description. Switch it off to quieten those screens. It "
        "cannot hide the markers that say a field reaches the model or is checked by "
        "code: those state where somebody's words end up, and stay whatever this is "
        "set to (ADR-046).",
    ),
    SettingSpec(
        key="ui.theme_locked",
        env="GREENLIGHT_AI_UI_THEME_LOCKED",
        label="Lock the theme",
        group="Appearance",
        kind="bool",
        default=True,
        help="On by default: both apps show the default theme and the picker is "
        "hidden, so everyone reviewing a delivery is looking at the same colours. "
        "Switch this off to let each person choose their own; nothing else changes, "
        "and the choice takes effect within the settings cache window.",
    ),
    # --- platform, read-only ----------------------------------------------------
    SettingSpec(
        key="platform.database_url",
        env="DATABASE_URL",
        label="Database URL",
        group="Platform",
        kind="str",
        default="sqlite+pysqlite:///./data/greenlight-ai.db",
        editable=False,
        restart=True,
        help="Where the data lives. Not editable here: a console that can change how "
        "it reaches its own database can lock everyone out of the thing they would "
        "use to fix it.",
    ),
    SettingSpec(
        key="platform.data_dir",
        env="GREENLIGHT_AI_DATA_DIR",
        label="Data directory",
        group="Platform",
        kind="str",
        default="./data",
        editable=False,
        restart=True,
        help="The shared volume holding uploads, reports, and PDFs. Changing it at "
        "runtime would orphan every stored file.",
    ),
    SettingSpec(
        key="platform.bind_host",
        env="GREENLIGHT_AI_BIND_HOST",
        label="Bind address",
        group="Platform",
        kind="str",
        default="127.0.0.1",
        editable=False,
        restart=True,
        help="What the API binds to. It decides whether the bootstrap-password refusal "
        "applies, so it is not something the console may soften.",
    ),
)

SETTINGS_BY_KEY: Final[dict[str, SettingSpec]] = {spec.key: spec for spec in SETTINGS}


def group_of(group: str) -> list[SettingSpec]:
    """The settings in one section, in declaration order.

    Args:
        group: The section name.

    Returns:
        Its settings.
    """
    return [spec for spec in SETTINGS if spec.group == group]
