"""Tests for the prompt preamble built from admin guidance (ADR-020).

The property that matters most is the negative one: with nothing configured the
preamble is empty, so every prompt is exactly what it was before this feature.
"""

from __future__ import annotations

from greenlight_ai.pipeline.guidance import MAX_CONTEXT_CHARS, RunGuidance, preamble


def test_nothing_configured_produces_no_preamble() -> None:
    """Configuring nothing changes nothing, which keeps the cache warm."""
    assert preamble(None) == ""
    assert preamble(RunGuidance()) == ""
    assert preamble(RunGuidance(artifact_context={"dirt": "   "}), "dirt") == ""


def test_scope_and_suppressions_appear_as_background() -> None:
    """The wording must mark this as context, never as a requirement."""
    text = preamble(
        RunGuidance(
            scope_label="Account Monitoring",
            scope_instructions="Prescreen opt-out must be honoured.",
            has_suppressions=True,
        )
    )
    assert "background rather than a requirement" in text
    assert "This delivery is Account Monitoring." in text
    assert "Suppressions were applied to it." in text
    assert "Prescreen opt-out must be honoured." in text
    assert text.endswith("\n\n")


def test_no_suppressions_is_stated_rather_than_left_out() -> None:
    """Silence reads as unknown; the form's default answer is an answer."""
    text = preamble(RunGuidance(scope_label="Archives", has_suppressions=False))
    assert "No suppressions were applied to it." in text


def test_artifact_guidance_is_included_only_for_its_own_artifact() -> None:
    """Guidance for the DIRT must not leak into the prompt about the OSL."""
    guidance = RunGuidance(
        scope_label="Archives",
        artifact_context={"dirt": "The last tab is masked.", "osl": "Skip the cover page."},
    )
    assert "The last tab is masked." in preamble(guidance, "dirt")
    assert "The last tab is masked." not in preamble(guidance, "osl")
    assert "Skip the cover page." in preamble(guidance, "osl")
    assert "Skip the cover page." not in preamble(guidance)


def test_long_guidance_is_clipped_at_a_word_boundary() -> None:
    """A prompt that is mostly preamble reads worse than one with none."""
    text = preamble(RunGuidance(scope_label="Other", scope_instructions="word " * 1000))
    assert "…" in text
    assert len(text) < MAX_CONTEXT_CHARS + 400
