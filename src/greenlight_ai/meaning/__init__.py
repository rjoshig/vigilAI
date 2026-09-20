"""Meaning: what a requirement answers to, per programme (Phase 6.10, ADR-033).

The model proposes requirement → configuration block → report cells from the samples
in scope; an administrator confirms; code compiles a confirmed entry into a shadow
check. Cell-level meaning (the validation guide) stays on the artifact type.
"""

from greenlight_ai.meaning.compile import compile_entry, retire_entry
from greenlight_ai.meaning.interview import propose
from greenlight_ai.meaning.render import meaning_lines
from greenlight_ai.meaning.samples import samples_in_scope

__all__ = ["compile_entry", "meaning_lines", "propose", "retire_entry", "samples_in_scope"]
