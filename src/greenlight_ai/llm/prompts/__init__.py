"""Versioned prompt templates for the LLM stages.

Each template carries a ``VERSION`` that is part of the cache key, so editing a prompt
refreshes results and nothing else does (ADR-005). Bump the version whenever the wording
changes; leaving it unchanged would serve stale answers from the cache.

Every prompt follows the same rules (``docs/llm-privacy.md``):

- One narrow task, small input, small output.
- JSON only, validated by a Pydantic schema.
- Never ask the model to compare numbers or do arithmetic; that is code's job (ADR-001).
- Never include a sample row or a non-aggregate report value.

The prompt versions here are provisional: they have not been validated against a real
model yet, and ADR-014 expects a bump after the first Gemma run.
"""

from greenlight_ai.llm.prompts.admin_classify import CLASSIFY_PROMPT
from greenlight_ai.llm.prompts.admin_draft import DRAFT_CHECK_PROMPT
from greenlight_ai.llm.prompts.admin_map import MAP_PROMPT
from greenlight_ai.llm.prompts.compliance_locate import COMPLIANCE_LOCATE_PROMPT
from greenlight_ai.llm.prompts.programme_reading import PROGRAMME_READING_PROMPT
from greenlight_ai.llm.prompts.judgment import JUDGMENT_PROMPT
from greenlight_ai.llm.prompts.name_locate import NAME_LOCATE_PROMPT
from greenlight_ai.llm.prompts.registry import PROMPTS, Prompt, get_prompt, prompt_versions
from greenlight_ai.llm.prompts.s2_extract import EXTRACT_PROMPT
from greenlight_ai.llm.prompts.s3_describe import DESCRIBE_PROMPT
from greenlight_ai.llm.prompts.s4_trace import TRACE_PROMPT
from greenlight_ai.llm.prompts.s8_coverage import COVERAGE_PROMPT
from greenlight_ai.llm.prompts.synthesize_critique import CRITIQUE_PROMPT
from greenlight_ai.llm.prompts.s8_lenses import LENSES, LENS_LABEL, LENS_PROMPTS, lens_prompt
from greenlight_ai.llm.prompts.s8_programme import PROGRAMME_PROMPT
from greenlight_ai.llm.prompts.s8_verify import VERIFY_PROMPT
from greenlight_ai.llm.prompts.s9_summarize import SUMMARIZE_PROMPT
from greenlight_ai.llm.prompts.synthesize import SYNTHESIZE_PROMPT

__all__ = [
    "CLASSIFY_PROMPT",
    "DESCRIBE_PROMPT",
    "DRAFT_CHECK_PROMPT",
    "MAP_PROMPT",
    "COMPLIANCE_LOCATE_PROMPT",
    "PROGRAMME_READING_PROMPT",
    "JUDGMENT_PROMPT",
    "NAME_LOCATE_PROMPT",
    "EXTRACT_PROMPT",
    "PROGRAMME_PROMPT",
    "PROMPTS",
    "Prompt",
    "SUMMARIZE_PROMPT",
    "SYNTHESIZE_PROMPT",
    "TRACE_PROMPT",
    "COVERAGE_PROMPT",
    "CRITIQUE_PROMPT",
    "VERIFY_PROMPT",
    "LENSES",
    "LENS_LABEL",
    "LENS_PROMPTS",
    "lens_prompt",
    "get_prompt",
    "prompt_versions",
]
