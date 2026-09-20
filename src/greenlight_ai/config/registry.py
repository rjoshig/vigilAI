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
        "usage survives. Shortening it deletes more at the next sweep.",
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
