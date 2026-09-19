"""Runtime settings: the admin console overrides the environment (ADR-023).

Precedence is **admin console, then `.env`, then the built-in default**. A setting an
administrator has never touched behaves exactly as it did when the only source was the
environment, which is what makes this safe to add to a running system.

Some settings are deliberately **not** editable at runtime: the database URL, the data
directory, the bind address, and the master key. A console that can change how it
reaches its own database can lock everyone out of the thing they would use to fix it.
Those are shown read-only, with the layer each value came from.
"""

from greenlight_ai.config.registry import SETTINGS, SettingSpec, group_of
from greenlight_ai.config.store import Resolved, effective, read_secret, resolve, write_setting

__all__ = [
    "SETTINGS",
    "SettingSpec",
    "Resolved",
    "effective",
    "group_of",
    "read_secret",
    "resolve",
    "write_setting",
]
