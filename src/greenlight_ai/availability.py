"""Whether the tool is accepting work, and starting it (Phase 6.14j).

Four switches, and the only thing that makes them safe is that one module resolves
them. Scattered checks are how a deployment ends up refusing submissions while the
banner still says everything is fine, or holding a queue that nothing is watching.

- **Seconds to change your mind.** A submitted run waits before the worker may pick it
  up. The queue already had `run_after`, so this is not a new mechanism — it is the
  existing one given a purpose. Inside that window the person who submitted can cancel
  and has spent nothing: no tokens, no model call, no partial state to unwind.
- **Hold the queue.** Submissions are accepted and pile up; nothing new starts. Work
  already running finishes, because killing a run halfway leaves a half-validated
  delivery and no reviewer can tell it from a whole one.
- **Stop accepting submissions.** New runs are refused with a message. Stronger than
  holding, and a different intent: hold when the backlog is fine, stop when it is not.
- **Maintenance mode.** The user app shows a maintenance page instead of itself, and it
  implies the other two. The admin console is deliberately exempt — a switch you cannot
  reach to turn off is a switch that strands you.

Everything here is code reading settings. No model is involved, and nothing here can
change what a run finds; it only decides when the run happens.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Final

from sqlalchemy.orm import Session

from greenlight_ai.config.store import resolve

__all__ = ["Availability", "read"]

_LOG: Final = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Availability:
    """What the tool is currently willing to do.

    Attributes:
        accepting: Whether a new run may be submitted.
        starting: Whether the worker may pick up queued work.
        maintenance: Whether the user app should show a maintenance page instead of
            itself. The console ignores this.
        message: What to tell somebody who is turned away.
        grace_seconds: How long a new run waits before it may be started, during which
            the submitter can cancel it for nothing.
    """

    accepting: bool = True
    starting: bool = True
    maintenance: bool = False
    message: str = ""
    grace_seconds: int = 30

    @property
    def grace(self) -> dt.timedelta:
        """The change-your-mind window as a duration.

        Returns:
            The window, which may be zero when an administrator wants runs to start at
            once.
        """
        return dt.timedelta(seconds=max(0, self.grace_seconds))


def read(session: Session) -> Availability:
    """Resolve the four switches into one answer.

    Args:
        session: An open session.

    Returns:
        What the tool is willing to do right now. Maintenance mode implies both of the
        others, so a caller never has to remember to check two things: asking whether
        it is accepting work is enough.
    """
    maintenance = bool(resolve(session, "maintenance.mode").value)
    accepting = not maintenance and not bool(resolve(session, "submissions.paused").value)
    starting = not maintenance and not bool(resolve(session, "queue.paused").value)
    return Availability(
        accepting=accepting,
        starting=starting,
        maintenance=maintenance,
        message=str(resolve(session, "maintenance.message").value),
        grace_seconds=int(resolve(session, "queue.grace_seconds").value),
    )
