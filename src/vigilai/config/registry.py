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
    "Uploads",
    "Retention",
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
        help="Stored encrypted and never shown again. Needs VIGILAI_SECRET_KEY to be "
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
        env="VIGILAI_TRAIN_AI_MODE",
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
        env="VIGILAI_TRAINING_SHADOW_DEFAULT",
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
        env="VIGILAI_TRAINING_REPLAY_RUNS",
        label="Recent runs used in a replay",
        group="Training",
        kind="int",
        default=25,
        minimum=0,
        maximum=500,
        help="How many finalized runs a candidate rule is tested against before "
        "approval. Zero replays the golden set alone and never reads a real run.",
    ),
    # --- login ----------------------------------------------------------------------
    SettingSpec(
        key="auth.admin",
        env="VIGILAI_ADMIN_AUTH",
        label="Require sign-in for the admin console",
        group="Login",
        kind="bool",
        default=False,
        help="Turning this off from the console is refused while you are signed in, "
        "because it would leave the console open to anyone who can reach it.",
    ),
    SettingSpec(
        key="auth.user",
        env="VIGILAI_USER_AUTH",
        label="Require sign-in for the user app",
        group="Login",
        kind="bool",
        default=False,
        help="With it off, every action is attributed to the placeholder account.",
    ),
    SettingSpec(
        key="auth.session_ttl_s",
        env="VIGILAI_SESSION_TTL_S",
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
        env="VIGILAI_SESSION_IDLE_S",
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
        env="VIGILAI_MIN_PASSWORD_LENGTH",
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
        env="VIGILAI_LOCKOUT_THRESHOLD",
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
        env="VIGILAI_LOCKOUT_S",
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
        env="VIGILAI_MAX_CONCURRENT_RUNS",
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
        env="VIGILAI_STARTS_PER_WINDOW",
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
        env="VIGILAI_RATE_WINDOW_S",
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
        env="VIGILAI_MAX_QUEUE_WAIT_S",
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
        env="VIGILAI_PER_ORDER_LIMIT",
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
        env="VIGILAI_MAX_UPLOAD_MB",
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
        env="VIGILAI_RETENTION_DAYS",
        label="Keep runs for (days)",
        group="Retention",
        kind="int",
        default=90,
        minimum=1,
        maximum=3650,
        help="Runs, their files, and their findings are deleted after this. Aggregated "
        "usage survives. Shortening it deletes more at the next sweep.",
    ),
    # --- platform, read-only ----------------------------------------------------
    SettingSpec(
        key="platform.database_url",
        env="DATABASE_URL",
        label="Database URL",
        group="Platform",
        kind="str",
        default="sqlite+pysqlite:///./data/vigilai.db",
        editable=False,
        restart=True,
        help="Where the data lives. Not editable here: a console that can change how "
        "it reaches its own database can lock everyone out of the thing they would "
        "use to fix it.",
    ),
    SettingSpec(
        key="platform.data_dir",
        env="VIGILAI_DATA_DIR",
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
        env="VIGILAI_BIND_HOST",
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
