"""Stage 3: describe each config block in requirement vocabulary, one call per block.

Technical blocks are classified by code first (connections, logging, scheduling) and
skipped, which saves a call each and keeps plumbing out of the reverse pass.
"""

from __future__ import annotations

import logging
from typing import Final

from vigilai.llm.prompts import DESCRIBE_PROMPT
from vigilai.llm.prompts.schemas import DescribeResponse, DescribedElement, ExtractedRequirement
from vigilai.parsers.config_json import is_technical
from vigilai.pipeline.context import RunContext
from vigilai.pipeline.s2_extract import to_rule
from vigilai.rules.schema import ConfigElement

__all__ = ["run"]

_LOG: Final = logging.getLogger(__name__)


def run(context: RunContext) -> None:
    """Describe every config block.

    Args:
        context: The run context, whose ``elements`` this fills.

    Raises:
        RuntimeError: When stage 1 has not run.
    """
    if context.config is None:
        raise RuntimeError("stage 3 requires stage 1 to have parsed the config")

    elements: list[ConfigElement] = []
    for block in context.config.blocks:
        element_id = f"C-{len(elements) + 1:03d}"

        if is_technical(block):
            elements.append(
                ConfigElement(
                    element_id=element_id,
                    json_path=block.json_path,
                    is_technical=True,
                    description=f"Technical configuration under {block.kind}.",
                    confidence=1.0,
                )
            )
            continue

        result = context.client.complete(
            DESCRIBE_PROMPT.system,
            DESCRIBE_PROMPT.render(block=block.as_text()),
            DESCRIBE_PROMPT.schema,
            stage="s3_describe",
            prompt_version=DESCRIBE_PROMPT.version,
        )
        response = result.parsed(DescribeResponse)
        described = _for_path(response, block.json_path)
        if described is None:
            elements.append(
                ConfigElement(
                    element_id=element_id,
                    json_path=block.json_path,
                    is_technical=True,
                    description="Not described by the model; treated as technical.",
                    confidence=0.0,
                )
            )
            continue

        elements.append(_to_element(described, element_id, block.json_path))

    context.elements = elements
    _LOG.info(
        "run %s stage 3: %d elements (%d technical)",
        context.run_id,
        len(elements),
        sum(1 for e in elements if e.is_technical),
    )


def _for_path(response: DescribeResponse, json_path: str) -> DescribedElement | None:
    """Pick the described element matching the block that was sent.

    A model asked about one block sometimes answers about several; taking only the
    matching path keeps an invented element from entering the run.

    Args:
        response: The model's answer.
        json_path: The block that was sent.

    Returns:
        The matching element, the sole element when the model omitted the path, or
        ``None``.
    """
    for element in response.elements:
        if element.json_path == json_path:
            return element
    if len(response.elements) == 1:
        return response.elements[0]
    return None


def _to_element(described: DescribedElement, element_id: str, json_path: str) -> ConfigElement:
    """Convert a described block into a config element.

    Args:
        described: What the model reported.
        element_id: The id to assign.
        json_path: The block's location.

    Returns:
        The element. A block the model could not type, or whose payload fails
        validation, is marked technical so it is excluded from the reverse pass rather
        than becoming a phantom requirement.
    """
    if described.is_technical or described.req_type is None:
        return ConfigElement(
            element_id=element_id,
            json_path=json_path,
            is_technical=True,
            description=described.description,
            confidence=described.confidence,
        )

    rule = to_rule(
        ExtractedRequirement(
            req_type=described.req_type,
            conditions=described.conditions,
            values=described.values,
            mode=described.mode,
            steps=described.steps,
            quantity=described.quantity,
            source_text=described.description,
            confidence=described.confidence,
        ),
        rule_id=element_id,
        source_ref=json_path,
        source="config",
    )
    if rule is None:
        return ConfigElement(
            element_id=element_id,
            json_path=json_path,
            is_technical=True,
            description=described.description or "Payload did not validate.",
            confidence=described.confidence,
        )
    return ConfigElement(
        element_id=element_id,
        json_path=json_path,
        rule=rule,
        is_technical=False,
        description=described.description,
        confidence=described.confidence,
    )
