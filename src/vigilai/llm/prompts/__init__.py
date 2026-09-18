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

from vigilai.llm.prompts.admin_draft import DRAFT_CHECK_PROMPT
from vigilai.llm.prompts.judgment import JUDGMENT_PROMPT
from vigilai.llm.prompts.registry import PROMPTS, Prompt, get_prompt, prompt_versions
from vigilai.llm.prompts.s2_extract import EXTRACT_PROMPT
from vigilai.llm.prompts.s3_describe import DESCRIBE_PROMPT
from vigilai.llm.prompts.s4_trace import TRACE_PROMPT
from vigilai.llm.prompts.s8_verify import VERIFY_PROMPT
from vigilai.llm.prompts.s9_summarize import SUMMARIZE_PROMPT

__all__ = [
    "DESCRIBE_PROMPT",
    "DRAFT_CHECK_PROMPT",
    "JUDGMENT_PROMPT",
    "EXTRACT_PROMPT",
    "PROMPTS",
    "Prompt",
    "SUMMARIZE_PROMPT",
    "TRACE_PROMPT",
    "VERIFY_PROMPT",
    "get_prompt",
    "prompt_versions",
]
