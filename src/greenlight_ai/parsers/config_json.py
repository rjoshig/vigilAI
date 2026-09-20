"""ETL config parser: JSON split into logical blocks with their JSON paths.

Implements :class:`greenlight_ai.parsers.base.ConfigParser` (ADR-006). The split is the only
judgement this module makes, and it is deliberate rather than generic: stage 3 describes
one block per call and stage 4 traces a requirement to a block, so blocks must be the
size of a single decision (one filter, one rule, one suppression, the field list).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from greenlight_ai.parsers.base import ConfigBlock, ConfigDocument, ParseError

__all__ = ["JsonConfigParser", "TECHNICAL_KEYS"]

_LOG: Final = logging.getLogger(__name__)

#: Config key families that describe plumbing rather than business rules. They are still
#: parsed (evidence may reference them) but stage 6's reverse pass ignores them, per the
#: category list in the admin-ui (``docs/design.md`` "Processing pipeline", step 6).
TECHNICAL_KEYS: Final[frozenset[str]] = frozenset(
    {"source", "sink", "logging", "schedule", "retry", "connection", "io", "runtime"}
)

#: Keys whose *elements* are separate blocks, because each element is one decision.
_LIST_KEYS: Final[frozenset[str]] = frozenset({"filters", "rules", "steps", "exclusions"})

#: Keys whose *members* are separate blocks, for the same reason.
_MAPPING_KEYS: Final[frozenset[str]] = frozenset({"rules", "suppressions", "thresholds"})


class JsonConfigParser:
    """Parses an ETL config JSON file into blocks."""

    def parse(self, path: Path) -> ConfigDocument:
        """Parse the config at ``path``.

        Args:
            path: The ``.json`` file to read.

        Returns:
            The parsed document, with one block per logical decision.

        Raises:
            ParseError: When the file is not valid JSON, is not a JSON object, or has no
                ``configuration_id``.
        """
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ParseError(path, f"could not be read ({exc.strerror})") from exc
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ParseError(path, f"is not valid JSON (line {exc.lineno}: {exc.msg})") from exc
        if not isinstance(decoded, dict):
            raise ParseError(path, "top level must be a JSON object")
        return self.parse_mapping(decoded, path)

    def parse_mapping(self, decoded: Mapping[str, Any], path: Path | None = None) -> ConfigDocument:
        """Parse an already decoded config.

        A captured configuration is stored as JSON in the database rather than as a
        file, and replaying a rule against it needs the same blocks a run saw
        (Phase 6.13e). Splitting is the same work; only the reading differs.

        Args:
            decoded: The configuration as a mapping.
            path: Where it came from, when it came from a file.

        Returns:
            The parsed document.

        Raises:
            ParseError: When it has no string ``configuration_id``.
        """
        source = path or Path("captured.json")
        configuration_id = decoded.get("configuration_id")
        if not isinstance(configuration_id, str) or not configuration_id.strip():
            raise ParseError(source, "missing a string 'configuration_id'")
        last_modified = decoded.get("last_modified")
        # The configuration usually names the customer it was built for. It is not
        # required — a file without one is a file without one, not a broken file — but
        # where it is present it is compared with what the submitter chose (ADR-041).
        customer = decoded.get("customer")

        blocks = tuple(_split(decoded))
        _LOG.info(
            "parsed config %s: %d blocks, configuration_id=%s",
            source.name,
            len(blocks),
            configuration_id,
        )
        return ConfigDocument(
            path=source,
            configuration_id=configuration_id.strip(),
            customer=customer.strip() if isinstance(customer, str) else "",
            last_modified=last_modified if isinstance(last_modified, str) else None,
            blocks=blocks,
            raw=decoded,
        )


def _split(document: Mapping[str, object]) -> Sequence[ConfigBlock]:
    """Split a decoded config into logical blocks.

    Args:
        document: The decoded top-level object.

    Returns:
        Blocks in document order. Scalars at the top level are grouped into a single
        ``"metadata"`` block so they do not each consume an LLM call.
    """
    blocks: list[ConfigBlock] = []
    metadata: dict[str, object] = {}

    for key, value in document.items():
        if isinstance(value, list) and key in _LIST_KEYS:
            for index, element in enumerate(value):
                blocks.append(ConfigBlock(json_path=f"{key}[{index}]", kind=key, content=element))
        elif isinstance(value, dict) and key in _MAPPING_KEYS:
            for name, element in value.items():
                blocks.append(ConfigBlock(json_path=f"{key}.{name}", kind=key, content=element))
        elif isinstance(value, (dict, list)):
            blocks.append(ConfigBlock(json_path=key, kind=key, content=value))
        else:
            metadata[key] = value

    if metadata:
        blocks.append(ConfigBlock(json_path="(metadata)", kind="metadata", content=metadata))
    return blocks


def is_technical(block: ConfigBlock) -> bool:
    """Say whether a block is plumbing rather than a business rule.

    Args:
        block: The block to classify.

    Returns:
        ``True`` when the block's key family is in :data:`TECHNICAL_KEYS`. Stage 3 may
        override this with the model's own ``is_technical`` judgement; this function is
        the cheap first pass that keeps such blocks out of the reverse pass.
    """
    return block.kind in TECHNICAL_KEYS or block.json_path.split(".")[0] in TECHNICAL_KEYS
