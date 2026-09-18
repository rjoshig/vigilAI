"""The prompt registry: one entry per LLM stage, each with its own version."""

from __future__ import annotations

from dataclasses import dataclass
from string import Template
from typing import Mapping

from pydantic import BaseModel

__all__ = ["Prompt", "PROMPTS", "get_prompt", "prompt_versions", "register"]


@dataclass(frozen=True, slots=True)
class Prompt:
    """One versioned prompt template.

    Attributes:
        stage: The pipeline stage that uses it, e.g. ``"s2_extract"``.
        version: The template version, part of the cache key. Bump on any wording change.
        system: The system prompt, fixed for the stage.
        template: The user prompt, with ``$name`` placeholders. ``$``-style rather than
            ``{}``-style because every prompt embeds worked examples of JSON output, and
            brace-style formatting would treat those braces as placeholders.
        schema: The Pydantic model the answer must satisfy.
    """

    stage: str
    version: str
    system: str
    template: str
    schema: type[BaseModel]

    def render(self, **values: object) -> str:
        """Fill the template.

        Args:
            **values: Placeholder values, one per ``$name`` in the template.

        Returns:
            The user prompt.

        Raises:
            KeyError: When a placeholder has no value, which is a programming error
                rather than a data problem, so it fails loudly rather than rendering a
                prompt with a hole in it.
        """
        return Template(self.template).substitute(**values)


_REGISTRY: dict[str, Prompt] = {}


def register(prompt: Prompt) -> Prompt:
    """Add a prompt to the registry.

    Args:
        prompt: The prompt to register.

    Returns:
        The same prompt, so module-level constants can be defined in one statement.

    Raises:
        ValueError: When a stage is registered twice, which would make the effective
            prompt depend on import order.
    """
    if prompt.stage in _REGISTRY:
        raise ValueError(f"stage {prompt.stage!r} is already registered")
    _REGISTRY[prompt.stage] = prompt
    return prompt


#: Every registered prompt, by stage.
PROMPTS: Mapping[str, Prompt] = _REGISTRY


def get_prompt(stage: str) -> Prompt:
    """Look up a prompt by stage.

    Args:
        stage: The pipeline stage name.

    Returns:
        The prompt.

    Raises:
        KeyError: When the stage has no prompt.
    """
    return _REGISTRY[stage]


def prompt_versions() -> dict[str, str]:
    """Report every stage's prompt version.

    Used in run metadata so a report can say which prompts produced it.

    Returns:
        Stage name to version.
    """
    return {stage: prompt.version for stage, prompt in sorted(_REGISTRY.items())}
