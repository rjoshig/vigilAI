"""The nine-stage pipeline and its orchestrator.

Stage modules are imported lazily by :mod:`vigilai.pipeline.run` to keep the import
graph flat; import the orchestrator, not a stage, from outside this package.
"""

from vigilai.pipeline.context import (
    RECHECK_STAGES,
    STAGE_ORDER,
    RunContext,
    StageName,
    StageRecord,
    StageStatus,
)

__all__ = [
    "RECHECK_STAGES",
    "RunContext",
    "STAGE_ORDER",
    "StageName",
    "StageRecord",
    "StageStatus",
]
