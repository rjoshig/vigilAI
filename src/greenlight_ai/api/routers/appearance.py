"""The look both apps start on, readable by anyone (Phase 6.6, ADR-031).

Not behind login: a browser has to know its theme before it knows who is using it,
and the answer carries nothing but a palette name and a switch.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from greenlight_ai.api.deps import get_session
from greenlight_ai.config import store
from greenlight_ai.config.registry import SETTINGS_BY_KEY

__all__ = ["router", "AppearanceOut"]

router = APIRouter(prefix="/appearance", tags=["meta"])


class AppearanceOut(BaseModel):
    """What every browser reads before it renders."""

    #: The palette the deployment starts on: console over environment over default.
    theme: str
    #: When true, the picker is hidden and the default applies everywhere.
    locked: bool = False
    #: Every palette the apps know, in picker order.
    palettes: list[str] = Field(default_factory=list)


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
    )
