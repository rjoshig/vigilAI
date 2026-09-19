"""Authentication: accounts, passwords, and sessions (ADR-022).

Login ships **off**. With both switches false the product behaves exactly as it did
before this package existed, because of one rule the whole design rests on: **there is
always a current user**. When login is off it is a seeded placeholder; when it is on it
is whoever signed in. Nothing stores a nullable author and no handler branches on
whether authentication is enabled.
"""

from greenlight_ai.auth.settings import AuthSettings

__all__ = ["AuthSettings"]
