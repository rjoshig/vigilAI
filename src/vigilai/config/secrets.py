"""Encrypting the one secret an administrator can set from the console (ADR-023).

The master key lives in the environment and never in the database, because a key
stored inside the thing it protects protects nothing. Without it, a secret is simply
not accepted for storage and the environment stays the only place it can come from —
refusing is a better answer than pretending.

``MultiFernet`` from the first day: it costs nothing and means rotating the master key
later is adding a key to the front of the list rather than a migration written under
pressure.
"""

from __future__ import annotations

import logging
import os
from typing import Final, Mapping

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

__all__ = ["SecretsUnavailable", "available", "decrypt", "encrypt", "last4", "master_keys"]

_LOG: Final = logging.getLogger(__name__)

#: Comma-separated, newest first. Every key decrypts; the first one encrypts.
_ENV_VAR: Final[str] = "VIGILAI_SECRET_KEY"


class SecretsUnavailable(RuntimeError):
    """Raised when a secret is offered for storage and no master key is configured."""


def master_keys(environ: Mapping[str, str] | None = None) -> list[str]:
    """The configured master keys, newest first.

    Args:
        environ: The mapping to read, defaulting to ``os.environ``.

    Returns:
        The keys, or an empty list when none is set.
    """
    source = os.environ if environ is None else environ
    return [part.strip() for part in source.get(_ENV_VAR, "").split(",") if part.strip()]


def available(environ: Mapping[str, str] | None = None) -> bool:
    """Whether secrets can be stored at all.

    Args:
        environ: The mapping to read.

    Returns:
        Whether a usable master key is configured.
    """
    return bool(master_keys(environ))


def _cipher(environ: Mapping[str, str] | None = None) -> MultiFernet:
    """Build the cipher from the configured keys.

    Args:
        environ: The mapping to read.

    Returns:
        A ``MultiFernet`` that encrypts with the newest key and decrypts with any.

    Raises:
        SecretsUnavailable: When no key is configured, or a key is malformed. Both are
            deployment mistakes, and failing loudly beats storing something that
            cannot be read back.
    """
    keys = master_keys(environ)
    if not keys:
        raise SecretsUnavailable(
            f"{_ENV_VAR} is not set, so a secret cannot be stored here. "
            "Generate one with Fernet.generate_key(), keep it outside the database, "
            "and back it up: losing it loses every secret it protects."
        )
    try:
        return MultiFernet([Fernet(key.encode("ascii")) for key in keys])
    except (ValueError, TypeError) as exc:
        raise SecretsUnavailable(f"{_ENV_VAR} is not a valid Fernet key") from exc


def encrypt(plaintext: str, environ: Mapping[str, str] | None = None) -> str:
    """Encrypt a secret for storage.

    Args:
        plaintext: The secret.
        environ: The mapping to read the master key from.

    Returns:
        The ciphertext, safe to store.

    Raises:
        SecretsUnavailable: When no master key is configured.
    """
    return _cipher(environ).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str, environ: Mapping[str, str] | None = None) -> str:
    """Read a stored secret back.

    Args:
        ciphertext: What was stored.
        environ: The mapping to read the master key from.

    Returns:
        The secret, or an empty string when it cannot be decrypted — which means the
        master key changed or was lost. An empty value makes the caller fall back to
        the environment, which is the only useful behaviour left at that point.

    Raises:
        SecretsUnavailable: When no master key is configured at all.
    """
    try:
        return _cipher(environ).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken:
        _LOG.error(
            "a stored secret cannot be decrypted: the master key has changed or been "
            "lost. Falling back to the environment for this value."
        )
        return ""


def last4(plaintext: str) -> str:
    """The tail of a secret, for showing that one is set.

    Args:
        plaintext: The secret.

    Returns:
        Its last four characters, or an empty string when it is too short to show any
        of without giving it away.
    """
    return plaintext[-4:] if len(plaintext) >= 8 else ""
