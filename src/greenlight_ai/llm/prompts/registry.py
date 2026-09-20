"""The prompt registry: one entry per LLM stage, each with its own version."""

from __future__ import annotations

from dataclasses import dataclass
from string import Template
from typing import Final, Mapping, Sequence

from pydantic import BaseModel

from greenlight_ai.llm import examples as example_library

__all__ = ["Prompt", "PROMPTS", "get_prompt", "prompt_versions", "register"]

#: Every template that carries worked examples puts them first and then begins the task
#: with a line starting "Now". That seam is where the administrator's library goes, and
#: every placeholder sits after it, so the same index applies to the rendered prompt.
_SEAM: Final[str] = "\nNow "


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

    def render_with_examples(
        self, library: Sequence[example_library.LibraryExample], **values: object
    ) -> str:
        """Fill the template, with the administrator's worked examples added.

        The library's examples are inserted after the built-in ones and before the task,
        numbered on from them, under a line saying they show the shape of a good answer
        and are not rules (ADR-038). They are added to the *rendered* prompt, so nothing
        an administrator wrote is ever treated as a template placeholder, and the text
        is part of what is hashed for the cache key.

        Args:
            library: The examples to add, already selected for this run's scope and
                capped. Empty renders exactly as :meth:`render` does.
            **values: Placeholder values, as for :meth:`render`.

        Returns:
            The user prompt.
        """
        rendered = self.render(**values)
        if not library:
            return rendered
        seam = self.template.find(_SEAM)
        if seam < 0:  # pragma: no cover - a stage with no seam takes no examples
            return rendered
        block = example_library.render_block(
            library, start=example_library.next_number(self.template)
        )
        return rendered[: seam + 1] + block + rendered[seam + 1 :]


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
