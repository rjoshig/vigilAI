"""Password hashing, using only the standard library (ADR-022).

`hashlib.scrypt` is a memory-hard key derivation function in the standard library, so
this adds no dependency and nothing here is hand-rolled cryptography. The stored string
carries its own parameters, so they can be raised later without invalidating the hashes
already in the table.

A password is never logged, never returned by an endpoint, and never put in an audit
entry.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
from typing import Final

__all__ = ["hash_password", "verify_password", "PasswordTooShort", "check_length"]

_LOG: Final = logging.getLogger(__name__)

#: scrypt cost parameters. n is the work factor; r and p are block size and
#: parallelism. These need about 16 MB per hash, which is the point: it makes a stolen
#: table expensive to attack and costs a signing-in human nothing.
_N: Final[int] = 2**14
_R: Final[int] = 8
_P: Final[int] = 1
_SALT_BYTES: Final[int] = 16
_KEY_BYTES: Final[int] = 32
_SCHEME: Final[str] = "scrypt"


class PasswordTooShort(ValueError):
    """Raised when a new password is below the configured minimum length."""


def check_length(password: str, minimum: int) -> None:
    """Enforce the one password composition rule there is.

    Args:
        password: The proposed password.
        minimum: The minimum length.

    Raises:
        PasswordTooShort: When it is too short. There is no complexity requirement and
            no expiry: both push people toward predictable passwords.
    """
    if len(password) < minimum:
        raise PasswordTooShort(f"a password must be at least {minimum} characters")


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    """Run scrypt.

    Args:
        password: The plaintext.
        salt: The per-user salt.
        n: Work factor.
        r: Block size.
        p: Parallelism.

    Returns:
        The derived key.
    """
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=_KEY_BYTES,
        maxmem=64 * 1024 * 1024,
    )


def hash_password(password: str) -> str:
    """Hash a password for storage.

    Args:
        password: The plaintext.

    Returns:
        ``scrypt$n$r$p$salt$hash``, with salt and hash base64-encoded. Self-describing,
        so a future increase in the cost parameters verifies old hashes unchanged.
    """
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = _derive(password, salt, _N, _R, _P)
    encoded_salt = base64.b64encode(salt).decode("ascii")
    encoded_hash = base64.b64encode(derived).decode("ascii")
    return f"{_SCHEME}${_N}${_R}${_P}${encoded_salt}${encoded_hash}"


def verify_password(password: str, stored: str) -> bool:
    """Check a password against a stored hash.

    Args:
        password: The plaintext offered.
        stored: The stored hash string.

    Returns:
        Whether they match. A malformed or empty stored value returns ``False`` rather
        than raising, because an account with no usable hash must simply fail to sign
        in — never succeed, and never take the service down.
    """
    if not stored:
        return False
    try:
        scheme, raw_n, raw_r, raw_p, encoded_salt, encoded_hash = stored.split("$")
        if scheme != _SCHEME:
            return False
        derived = _derive(
            password, base64.b64decode(encoded_salt), int(raw_n), int(raw_r), int(raw_p)
        )
    except (ValueError, TypeError):
        _LOG.warning("a stored password hash is malformed; refusing the sign-in")
        return False
    return hmac.compare_digest(derived, base64.b64decode(encoded_hash))
