"""The look both apps start on, readable by anyone (Phase 6.6, ADR-031).

Not behind login: a browser has to know its theme before it knows who is using it,
and the answer carries nothing but a palette name and a switch.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from greenlight_ai.api.deps import get_session
from greenlight_ai import announcements
from greenlight_ai.config import store
from greenlight_ai.config.registry import SETTINGS_BY_KEY

__all__ = ["router", "AppearanceOut"]

router = APIRouter(prefix="/appearance", tags=["meta"])

#: Notices are read by the same browsers at the same moment, and are their own
#: resource rather than part of the appearance answer: one is about how the app
#: looks and the other about what it has to say.
notices_router = APIRouter(prefix="/notices", tags=["meta"])


class AppearanceOut(BaseModel):
    """What every browser reads before it renders."""

    #: The palette the deployment starts on: console over environment over default.
    theme: str
    #: When true, the picker is hidden and the default applies everywhere.
    locked: bool = False
    #: Every palette the apps know, in picker order.
    palettes: list[str] = Field(default_factory=list)
    #: Whether the consoles explain each screen (Phase 6.14d). On by default; an
    #: administrator who knows the product can switch it off. It never hides the
    #: markers that say which fields reach the model: those are facts about the run.
    tooltips: bool = True
    #: The line under the mark in both apps' sidebars (Phase 6.14h).
    tagline: str = ""


@router.get("", response_model=AppearanceOut)
def appearance(session: Session = Depends(get_session)) -> AppearanceOut:
    """The default theme and whether it is locked.

    Args:
        session: The request's session.

    Returns:
        The resolved appearance settings (ADR-023: console over ``.env`` over default).
    """
    return AppearanceOut(
        theme=str(store.resolve(session, "ui.theme").value),
        locked=bool(store.resolve(session, "ui.theme_locked").value),
        palettes=list(SETTINGS_BY_KEY["ui.theme"].choices),
        tooltips=bool(store.resolve(session, "ui.tooltips").value),
        tagline=str(store.resolve(session, "ui.tagline").value),
    )


class NoticeOut(BaseModel):
    """One notice showing at the top of an app right now (Phase 6.14g)."""

    id: int
    #: ``info`` · ``warning`` · ``critical``.
    level: str = "info"
    message: str = ""


@notices_router.get("", response_model=list[NoticeOut])
def notices(
    audience: str = Query(default="user", pattern="^(user|admin)$"),
    session: Session = Depends(get_session),
) -> list[NoticeOut]:
    """What this app should be showing at the top of the page, right now.

    Unauthenticated like the appearance answer beside it: a maintenance notice is most
    useful to somebody who has not signed in yet, and it carries nothing that is not
    already meant for everyone using the app.

    Args:
        audience: Which app is asking.
        session: The request's session.

    Returns:
        The notices in force, most serious first. Empty almost always, which is the
        point: a banner that is always there is not read.
    """
    return [
        NoticeOut(id=row.id, level=row.level, message=row.message)
        for row in announcements.showing_now(session, audience)
    ]
