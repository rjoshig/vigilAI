"""Admin endpoints: templates, named values, checks, compliance, reference data, usage.

Checks are defined as data, not code. The model helps write one *once*
(``POST /admin/checks/draft``); after that the check runs as code on every request at no
token cost (``docs/design.md`` "Configurable checks"). Testing a check never calls the
model.
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Sequence, cast

import sqlalchemy as sa
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from greenlight_ai.api import schemas_admin as wire
from greenlight_ai.api.deps import (
    CurrentUser,
    current_user,
    get_data_dir,
    get_session,
    require_admin,
)
from greenlight_ai.api.uploads import UploadError, store_upload
from greenlight_ai.checks.expressions import (
    ExpressionError,
    UnresolvedValue,
    evaluate,
    referenced_names,
    validate,
)
from greenlight_ai.checks import guides
from greenlight_ai.checks.named_values import NamedValue, resolve, to_number
from greenlight_ai.db import catalog, models, repository, versions
from greenlight_ai.llm.cache import LLMCache
from greenlight_ai.llm.client import LLMError
from greenlight_ai.llm.factory import build_client
from greenlight_ai.llm.prompts import DRAFT_CHECK_PROMPT
from greenlight_ai.llm.prompts.schemas import DraftCheckResponse
from greenlight_ai.parsers.base import ParseError, ReportKind
from greenlight_ai.parsers.masking import DEFAULT_MASKED_COLUMNS
from greenlight_ai.parsers.reports.xlsx import PARSERS, parser_for

__all__ = ["router"]

_LOG: Final = logging.getLogger(__name__)

# Every route here needs an administrator, the read-only ones included: a listing
# tells a caller what the tool checks and who its customers are.
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])

#: Where uploaded sample workbooks live on the shared volume.
TEMPLATE_DIR: Final[str] = "templates"

#: An artifact key is used as a multipart field name and a filename, so it is kept to
#: characters that are safe in both.
_KEY_RE: Final = re.compile(r"^[a-z][a-z0-9_]{1,59}$")

#: A scope code is short and appears in the UI and on the run row.
_CODE_RE: Final = re.compile(r"^[A-Z0-9_]{2,20}$")

#: Starlette renamed its 422 constant; the number is stable.
HTTP_422: Final[int] = 422


# ---------------------------------------------------------------- artifact types


def _sheets(path: Path, key: str) -> list[str]:
    """List a sample workbook's sheets, for the admin-ui's locator pickers.

    Args:
        path: The stored workbook.
        key: The artifact key, which selects the parser.

    Returns:
        The sheet names, or an empty list when the file cannot be read.
    """
    if not path.exists():
        return []
    try:
        return [sheet.name for sheet in parser_for(key).parse(path).sheets]
    except ParseError:
        return []


#: The most samples one artifact type may hold. Enough to show how a layout varies
#: between customers, few enough that an administrator reads them all (ADR-021).
MAX_SAMPLES: Final[int] = 3

#: How many populated cells a preview returns per sheet. A person scanning for where
#: a value lives reads the top of a sheet, not four thousand rows of it.
PREVIEW_CELLS: Final[int] = 400


def _get_sample(session: Session, key: str, sample_id: int) -> models.ArtifactSample:
    """Fetch one sample, checking it belongs to the type in the path.

    Args:
        session: The request's session.
        key: The artifact key.
        sample_id: The sample.

    Returns:
        The sample.

    Raises:
        HTTPException: 404 when it does not exist or belongs to another type.
    """
    sample = session.get(models.ArtifactSample, sample_id)
    if sample is None or sample.artifact_type.key != key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"sample {sample_id} not found for {key!r}")
    return sample


def _sheet_preview(sheet: Any, masked: tuple[str, ...]) -> wire.SheetPreview:
    """Render one sheet's populated cells for the console.

    Args:
        sheet: The parsed sheet.
        masked: The masked-column patterns, applied at parse time already; the names
            are reported so the console can say why a column reads as ``[masked]``.

    Returns:
        The preview, truncated to the first few hundred populated cells. The label to
        a cell's left is included because that is how a named value should point at
        it: a label survives an inserted row and a cell address does not.
    """
    cells: list[wire.CellPreview] = []
    for row_index, row in enumerate(sheet.rows, start=1):
        first_text = ""
        for cell in row:
            if isinstance(cell.value, str) and cell.value.strip():
                first_text = cell.value.strip()
                break
        for column_index, cell in enumerate(row, start=1):
            if cell.value is None or str(cell.value).strip() == "":
                continue
            if len(cells) >= PREVIEW_CELLS:
                break
            text = str(cell.value)
            cells.append(
                wire.CellPreview(
                    cell=cell.address,
                    value=text[:200],
                    label=first_text[:200] if text != first_text else "",
                    row=row_index,
                    column=column_index,
                )
            )
        if len(cells) >= PREVIEW_CELLS:
            break

    del masked  # applied at parse time; kept in the signature so the reason is visible
    return wire.SheetPreview(
        name=sheet.name,
        rows=len(sheet.rows),
        columns=len(sheet.header) if sheet.header else 0,
        cells=cells,
    )


def _artifact_out(
    row: models.ArtifactType, data_dir: Path, in_use: int = 0
) -> wire.ArtifactTypeOut:
    """Build the wire model for one artifact type.

    Args:
        row: The stored type.
        data_dir: The shared volume.
        in_use: How many runs have uploaded this type.

    Returns:
        The wire model, including the sample's sheets when there is one.
    """
    samples = [
        wire.SampleOut(
            id=sample.id,
            label=sample.label,
            filename=sample.filename,
            sheets=list(sample.sheets or []),
            size_bytes=sample.size_bytes,
            notes=sample.notes,
            uploaded_by=sample.uploaded_by,
            created_at=sample.created_at,
        )
        for sample in row.samples
    ]
    # Every sheet across every sample, de-duplicated but in first-seen order: a named
    # value's sheet may exist in one customer's layout and not another's, and the
    # picker has to offer both.
    sheets: list[str] = []
    for sample in samples:
        for name in sample.sheets:
            if name not in sheets:
                sheets.append(name)
    # The column is a plain string so a future kind needs no migration; the wire model
    # narrows it, and an unrecognised value would be a bug in whatever wrote the row.
    kind = cast(Literal["osl", "config", "report"], row.kind)
    return wire.ArtifactTypeOut(
        id=row.id,
        key=row.key,
        label=row.label,
        kind=kind,
        description=row.description,
        ai_context=row.ai_context,
        is_active=row.is_active,
        is_required=row.is_required,
        is_builtin=row.is_builtin,
        sort_order=row.sort_order,
        samples=samples,
        sheets=sheets,
        runs_using=in_use,
        guide=[guides.GuideEntry.model_validate(entry) for entry in row.guide_entries or []],
    )


@router.get("/artifact-types", response_model=list[wire.ArtifactTypeOut])
def list_artifact_types(
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    _user: CurrentUser = Depends(current_user),
) -> list[wire.ArtifactTypeOut]:
    """List every input the tool accepts, active or not.

    Args:
        session: The request's session.
        data_dir: The shared volume.
        _user: The caller.

    Returns:
        The artifact types in display order, seeding the shipped defaults into an
        empty database first so a fresh install is configurable rather than blank.
    """
    catalog.seed_defaults(session)
    rows = list(
        session.execute(
            sa.select(models.ArtifactType).order_by(
                models.ArtifactType.sort_order, models.ArtifactType.key
            )
        ).scalars()
    )
    counts: dict[str, int] = {
        str(kind): int(count)
        for kind, count in session.execute(
            sa.select(models.RunFile.kind, sa.func.count()).group_by(models.RunFile.kind)
        ).all()
    }
    return [_artifact_out(row, data_dir, counts.get(row.key, 0)) for row in rows]


@router.post(
    "/artifact-types", response_model=wire.ArtifactTypeOut, status_code=status.HTTP_201_CREATED
)
def save_artifact_type(
    payload: wire.ArtifactTypeIn,
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    user: CurrentUser = Depends(current_user),
) -> wire.ArtifactTypeOut:
    """Create a report type, or edit any type's description, guidance, or state.

    Args:
        payload: The type.
        session: The request's session.
        data_dir: The shared volume.
        user: The caller.

    Returns:
        The stored type.

    Raises:
        HTTPException: 422 when the key is malformed, or when a built-in's key or kind
            is being changed — those are referenced by the fixed report checks.
    """
    require_admin(user)
    catalog.seed_defaults(session)

    key = payload.key.strip().lower()
    if not _KEY_RE.match(key):
        raise HTTPException(
            HTTP_422,
            f"{key!r} is not a valid key: use lowercase letters, digits, and underscores",
        )

    row = session.execute(
        sa.select(models.ArtifactType).where(models.ArtifactType.key == key)
    ).scalar_one_or_none()

    if row is None:
        row = models.ArtifactType(key=key, kind="report", is_builtin=False)
        session.add(row)
    elif row.is_builtin and payload.kind and payload.kind != row.kind:
        raise HTTPException(
            HTTP_422,
            f"{key!r} is a built-in type; its kind cannot be changed because the fixed "
            "report checks look for it by key",
        )

    row.label = payload.label.strip() or key
    if not row.is_builtin and payload.kind:
        row.kind = payload.kind
    row.description = payload.description
    row.ai_context = payload.ai_context
    row.is_active = payload.is_active
    row.is_required = payload.is_required
    row.sort_order = payload.sort_order
    session.flush()

    repository.audit(session, "admin.artifact_type_saved", detail=key)
    versions.record_artifact_version(session, row, user.name)
    return _artifact_out(row, data_dir)


@router.post(
    "/artifact-types/{key}/samples",
    response_model=wire.ArtifactTypeOut,
    status_code=status.HTTP_201_CREATED,
)
def upload_sample(
    key: str,
    file: Annotated[UploadFile, File()],
    label: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    user: CurrentUser = Depends(require_admin),
) -> wire.ArtifactTypeOut:
    """Add a sample to an artifact type, up to three.

    Args:
        key: The artifact key.
        label: What distinguishes this sample from the others, such as the customer
            or the year.
        notes: Anything worth saying about it.
        file: The sample.
        session: The request's session.
        data_dir: The shared volume.
        user: The calling administrator.

    Returns:
        The updated type with all of its samples.

    Raises:
        HTTPException: 404 when the type does not exist, 400 when the upload is
            rejected, and 409 when three samples are already stored. Three is enough
            to show how a layout varies and few enough that an administrator reads
            them all; the fourth is refused rather than silently dropping one.
    """
    catalog.seed_defaults(session)
    row = session.execute(
        sa.select(models.ArtifactType).where(models.ArtifactType.key == key)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"artifact type {key!r} not found")
    if len(row.samples) >= MAX_SAMPLES:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{key!r} already has {MAX_SAMPLES} samples; remove one before adding another",
        )

    try:
        stored = store_upload(
            file.file,
            file.filename or f"{key}.xlsx",
            file.content_type or "",
            key,
            data_dir,
            # One directory per sample: three samples of one type must not share a
            # path, and an old version's workbook must outlive the sample row (ADR-029).
            f"{TEMPLATE_DIR}/{uuid.uuid4().hex[:12]}",
        )
    except UploadError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    sample = models.ArtifactSample(
        artifact_type_id=row.id,
        label=label.strip(),
        notes=notes.strip(),
        filename=stored.filename,
        storage_path=stored.storage_key,
        sha256=stored.sha256,
        size_bytes=stored.size_bytes,
        # Read once here so the console and the type detector never have to open the
        # workbook again, which is the slow part of both.
        sheets=_sheets(data_dir / stored.storage_key, key),
        uploaded_by_user_id=user.id,
        uploaded_by=user.name,
    )
    session.add(sample)
    session.flush()
    session.refresh(row)
    repository.audit(session, "admin.sample_uploaded", detail=key, user_id=user.id, actor=user.name)
    versions.record_artifact_version(session, row, user.name, "sample added")
    return _artifact_out(row, data_dir)


@router.put("/artifact-types/{key}/guide", response_model=wire.ArtifactTypeOut)
def save_guide(
    key: str,
    payload: wire.GuideIn,
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    user: CurrentUser = Depends(require_admin),
) -> wire.ArtifactTypeOut:
    """Replace an artifact type's validation guide (Phase 6.8b, ADR-029).

    Examples are filled by resolving each locator on the stored samples. An entry
    with an example and a config path compiles into a shadow check with origin
    ``guide``; the rest is background for the model. The save is a version.

    Args:
        key: The artifact key.
        payload: The entries, in order.
        session: The request's session.
        data_dir: The shared volume.
        user: The calling administrator.

    Returns:
        The type, with the guide's examples filled.

    Raises:
        HTTPException: 404 when the type does not exist, 422 when two entries share
            an id.
    """
    catalog.seed_defaults(session)
    row = session.execute(
        sa.select(models.ArtifactType).where(models.ArtifactType.key == key)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"artifact type {key!r} not found")
    ids = [entry.id for entry in payload.entries]
    if len(set(ids)) != len(ids):
        raise HTTPException(HTTP_422, "every guide entry needs its own id")

    entries = guides.fill_examples(key, payload.entries, row.samples, data_dir)
    row.guide_entries = [entry.model_dump(by_alias=True) for entry in entries]
    compiled = guides.compile_checks(session, key, entries, user.name)
    session.flush()
    repository.audit(
        session,
        "admin.guide_saved",
        detail=f"{key}:{len(entries)} entries, {compiled} checks",
        user_id=user.id,
        actor=user.name,
    )
    versions.record_artifact_version(session, row, user.name, "guide edited")
    return _artifact_out(row, data_dir)


@router.get("/artifact-types/{key}/samples/{sample_id}/download")
def download_sample(
    key: str,
    sample_id: int,
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    user: CurrentUser = Depends(require_admin),
) -> FileResponse:
    """Download a stored sample.

    An administrator has to be able to see the sample in use; describing it is not
    the same as opening it.

    Args:
        key: The artifact key.
        sample_id: The sample.
        session: The request's session.
        data_dir: The shared volume.
        user: The calling administrator.

    Returns:
        The file, under the name it was uploaded with.

    Raises:
        HTTPException: 404 when the sample or its file is missing.
    """
    sample = _get_sample(session, key, sample_id)
    path = data_dir / sample.storage_path
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "the stored file is missing")
    repository.audit(
        session,
        "admin.sample_downloaded",
        detail=f"{key}/{sample_id}",
        user_id=user.id,
        actor=user.name,
    )
    return FileResponse(
        path,
        filename=sample.filename or f"{key}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get(
    "/artifact-types/{key}/samples/{sample_id}/preview",
    response_model=wire.SamplePreviewOut,
)
def preview_sample(
    key: str,
    sample_id: int,
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    _user: CurrentUser = Depends(require_admin),
) -> wire.SamplePreviewOut:
    """Show what a sample contains, cell by cell.

    This is what someone reads while deciding what a report means and where a named
    value should point. Values pass through the same masking as a real upload,
    because a sample is a file that may hold customer data (ADR-003).

    Args:
        key: The artifact key.
        sample_id: The sample.
        session: The request's session.
        data_dir: The shared volume.
        _user: The calling administrator.

    Returns:
        Each sheet with its populated cells, their addresses, and the label to the
        left of each one where there is one.

    Raises:
        HTTPException: 404 when the sample is missing, 422 when it cannot be parsed.
    """
    sample = _get_sample(session, key, sample_id)
    path = data_dir / sample.storage_path
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "the stored file is missing")
    try:
        document = parser_for(key).parse(path)
    except ParseError as exc:
        raise HTTPException(HTTP_422, f"the sample could not be read: {exc}") from exc

    masked = repository.load_masked_columns(session)
    return wire.SamplePreviewOut(
        sample_id=sample.id,
        filename=sample.filename,
        sheets=[_sheet_preview(sheet, masked) for sheet in document.sheets],
    )


@router.delete("/artifact-types/{key}/samples/{sample_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sample(
    key: str,
    sample_id: int,
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    user: CurrentUser = Depends(require_admin),
) -> None:
    """Remove one sample.

    Args:
        key: The artifact key.
        sample_id: The sample.
        session: The request's session.
        data_dir: The shared volume.
        user: The calling administrator.

    Raises:
        HTTPException: 404 when it does not exist.
    """
    sample = _get_sample(session, key, sample_id)
    row = sample.artifact_type
    session.delete(sample)
    session.flush()
    repository.audit(
        session,
        "admin.sample_deleted",
        detail=f"{key}/{sample_id}",
        user_id=user.id,
        actor=user.name,
    )
    versions.record_artifact_version(session, row, user.name, "sample removed")
    # The workbook stays on disk while any retained version still names it, so a
    # revert can bring it back; the retention sweep removes it once none does.


@router.delete("/artifact-types/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_artifact_type(
    key: str,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> None:
    """Delete an admin-defined report type.

    Args:
        key: The artifact key.
        session: The request's session.
        user: The caller.

    Raises:
        HTTPException: 404 when it does not exist; 409 when it is a built-in, or when
            a run has already used it. Deleting either would leave stored runs
            referring to a type nothing can describe — disabling it is the right move,
            and it keeps the history readable.
    """
    require_admin(user)
    row = session.execute(
        sa.select(models.ArtifactType).where(models.ArtifactType.key == key)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"artifact type {key!r} not found")
    if row.is_builtin:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{key!r} is a built-in type and cannot be deleted; switch it off instead",
        )

    used = int(
        session.execute(
            sa.select(sa.func.count()).select_from(models.RunFile).where(models.RunFile.kind == key)
        ).scalar_one()
    )
    if used:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{used} run(s) have uploaded {key!r}; switch it off instead so their history "
            "stays readable",
        )

    session.delete(row)
    session.execute(
        sa.delete(models.DefinitionVersion).where(
            models.DefinitionVersion.kind == "artifact_type",
            models.DefinitionVersion.object_key == key,
        )
    )
    repository.audit(session, "admin.artifact_type_deleted", detail=key)


# ------------------------------------------------------------------------- scopes


@router.get("/scopes", response_model=list[wire.ScopeOut])
def list_scopes(
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> list[wire.ScopeOut]:
    """List the delivery programmes and their standing instructions.

    Args:
        session: The request's session.
        _user: The caller.

    Returns:
        The scopes in display order.
    """
    catalog.seed_defaults(session)
    counts: dict[str, int] = {
        str(scope): int(count)
        for scope, count in session.execute(
            sa.select(models.Run.scope, sa.func.count()).group_by(models.Run.scope)
        ).all()
    }
    rows = session.execute(
        sa.select(models.RunScope).order_by(models.RunScope.sort_order, models.RunScope.code)
    ).scalars()
    return [
        wire.ScopeOut(
            id=row.id,
            code=row.code,
            label=row.label,
            description=row.description,
            standing_instructions=row.standing_instructions,
            is_active=row.is_active,
            sort_order=row.sort_order,
            keywords=list(row.keywords or []),
            runs_using=counts.get(row.code, 0),
        )
        for row in rows
    ]


@router.post("/scopes", response_model=wire.ScopeOut, status_code=status.HTTP_201_CREATED)
def save_scope(
    payload: wire.ScopeIn,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> wire.ScopeOut:
    """Create or edit a delivery programme.

    Standing instructions are passed to the model as background, never as an OSL
    requirement (ADR-020), so this is where a compliance regime that the OSL does not
    restate gets written down once.

    Args:
        payload: The scope.
        session: The request's session.
        user: The caller.

    Returns:
        The stored scope.

    Raises:
        HTTPException: 422 when the code is malformed.
    """
    require_admin(user)
    catalog.seed_defaults(session)

    code = payload.code.strip().upper()
    if not _CODE_RE.match(code):
        raise HTTPException(
            HTTP_422, f"{code!r} is not a valid code: use 2 to 20 letters, digits, or underscores"
        )

    row = session.execute(
        sa.select(models.RunScope).where(models.RunScope.code == code)
    ).scalar_one_or_none()
    if row is None:
        row = models.RunScope(code=code)
        session.add(row)

    row.label = payload.label.strip() or code
    row.description = payload.description
    row.standing_instructions = payload.standing_instructions
    row.is_active = payload.is_active
    row.sort_order = payload.sort_order
    row.keywords = [word.strip() for word in payload.keywords if word.strip()]
    session.flush()

    repository.audit(session, "admin.scope_saved", detail=code)
    return wire.ScopeOut(
        id=row.id,
        code=row.code,
        label=row.label,
        description=row.description,
        standing_instructions=row.standing_instructions,
        is_active=row.is_active,
        sort_order=row.sort_order,
        keywords=list(row.keywords or []),
    )


@router.delete("/scopes/{code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scope(
    code: str,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> None:
    """Delete a delivery programme.

    Args:
        code: The scope code.
        session: The request's session.
        user: The caller.

    Raises:
        HTTPException: 404 when it does not exist, 409 when runs already reference it.
    """
    require_admin(user)
    row = session.execute(
        sa.select(models.RunScope).where(models.RunScope.code == code.upper())
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"scope {code!r} not found")

    used = int(
        session.execute(
            sa.select(sa.func.count()).select_from(models.Run).where(models.Run.scope == row.code)
        ).scalar_one()
    )
    if used:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{used} run(s) are in {row.code!r}; switch it off instead so their history "
            "stays readable",
        )
    session.delete(row)
    repository.audit(session, "admin.scope_deleted", detail=row.code)


def _load_templates(session: Session, data_dir: Path) -> dict[ReportKind, Any]:
    """Parse every uploaded sample workbook.

    Args:
        session: An open session.
        data_dir: The shared volume.

    Returns:
        Report kind to parsed document, skipping any that cannot be read. A check
        tested against a missing sample reports "could not resolve", which is the same
        answer the run would give.
    """
    documents: dict[ReportKind, Any] = {}
    rows = session.execute(
        sa.select(models.ArtifactType).where(models.ArtifactType.kind == "report")
    ).scalars()
    for row in rows:
        for sample in row.samples:
            path = data_dir / sample.storage_path
            if not path.exists():
                continue
            try:
                # The first readable sample is the one a check is tested against. The
                # others exist so a named value's resolution can be shown against each
                # layout, which is where a pointer that only works on one shows up.
                documents[row.key] = parser_for(row.key).parse(path)
                break
            except ParseError as exc:
                _LOG.info("sample for %s could not be parsed: %s", row.key, exc)
    return documents


# ------------------------------------------------------------------- named values


def _to_named_value(row: models.NamedValueRow) -> NamedValue:
    """Convert a stored row into the resolver's value object.

    Args:
        row: The stored pointer.

    Returns:
        The named value.
    """
    locator = row.locator or {}
    return NamedValue(
        name=row.name,
        report_kind=row.report_type,
        sheet=row.sheet,
        kind=locator.get("kind", "label"),
        cell=locator.get("cell", ""),
        label=locator.get("label", ""),
        label_column=locator.get("label_column", 0),
        value_column=locator.get("value_column", 1),
        description=row.description,
    )


@router.get("/named-values", response_model=list[wire.NamedValueOut])
def list_named_values(
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    _user: CurrentUser = Depends(current_user),
) -> list[wire.NamedValueOut]:
    """List the named values, with what each resolves to on the samples.

    Showing the resolved value is the point: a pointer that no longer finds anything is
    the failure mode this screen exists to catch.

    Args:
        session: The request's session.
        data_dir: The shared volume.
        _user: The caller.

    Returns:
        The named values.
    """
    documents = _load_templates(session, data_dir)
    checks = list(session.execute(sa.select(models.CheckDefinitionRow)).scalars())

    out: list[wire.NamedValueOut] = []
    for row in session.execute(
        sa.select(models.NamedValueRow).order_by(models.NamedValueRow.name)
    ).scalars():
        named = _to_named_value(row)
        value = resolve(named, documents)
        used_by = [
            check.name
            for check in checks
            if check.expression and row.name in _safe_references(check.expression)
        ]
        locator = row.locator or {}
        out.append(
            wire.NamedValueOut(
                id=row.id,
                name=row.name,
                report_type=row.report_type,
                sheet=row.sheet,
                kind=locator.get("kind", "label"),
                cell=locator.get("cell", ""),
                label=locator.get("label", ""),
                label_column=locator.get("label_column", 0),
                value_column=locator.get("value_column", 1),
                description=row.description,
                resolved=None if value is None else str(value),
                used_by=used_by,
            )
        )
    return out


def _safe_references(expression: str) -> frozenset[str]:
    """Names an expression uses, treating a malformed one as using nothing.

    Args:
        expression: The check expression.

    Returns:
        The referenced names, empty when the expression does not parse.
    """
    try:
        return referenced_names(expression)
    except ExpressionError:
        return frozenset()


def _locator(payload: wire.NamedValueIn) -> dict[str, Any]:
    """Build the stored locator from a submitted pointer.

    Args:
        payload: The submitted pointer.

    Returns:
        The locator as it is stored.
    """
    return {
        "kind": payload.kind,
        "cell": payload.cell,
        "label": payload.label,
        "label_column": payload.label_column,
        "value_column": payload.value_column,
    }


@router.post(
    "/named-values", response_model=wire.NamedValueOut, status_code=status.HTTP_201_CREATED
)
def create_named_value(
    payload: wire.NamedValueIn,
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    user: CurrentUser = Depends(current_user),
) -> wire.NamedValueOut:
    """Create or replace a named value.

    Args:
        payload: The pointer.
        session: The request's session.
        data_dir: The shared volume.
        user: The caller.

    Returns:
        The stored pointer with what it resolves to.
    """
    require_admin(user)
    row = session.execute(
        sa.select(models.NamedValueRow).where(models.NamedValueRow.name == payload.name)
    ).scalar_one_or_none()
    if row is None:
        row = models.NamedValueRow(name=payload.name)
        session.add(row)
    row.report_type = payload.report_type
    row.sheet = payload.sheet
    row.locator = _locator(payload)
    row.description = payload.description
    session.flush()

    value = resolve(_to_named_value(row), _load_templates(session, data_dir))
    repository.audit(session, "admin.named_value_saved", detail=payload.name)
    return wire.NamedValueOut(
        id=row.id, **payload.model_dump(), resolved=None if value is None else str(value)
    )


@router.delete("/named-values/{value_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_named_value(
    value_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> None:
    """Delete a named value.

    Args:
        value_id: The row id.
        session: The request's session.
        user: The caller.

    Raises:
        HTTPException: 404 when it does not exist, 409 when a check still refers to it.
            Deleting it anyway would turn a working check into "could not evaluate" on
            the next run, with nothing to point at.
    """
    require_admin(user)
    row = session.get(models.NamedValueRow, value_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"named value {value_id} not found")

    users = [
        check.name
        for check in session.execute(sa.select(models.CheckDefinitionRow)).scalars()
        if row.name in _safe_references(check.expression)
    ]
    if users:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{row.name} is used by {', '.join(users)}; edit or remove those checks first",
        )
    session.delete(row)
    repository.audit(session, "admin.named_value_deleted", detail=row.name)


# -------------------------------------------------------------------------- checks


@router.get("/checks", response_model=list[wire.CheckOut])
def list_checks(
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> list[wire.CheckOut]:
    """List every check, active or not.

    Args:
        session: The request's session.
        _user: The caller.

    Returns:
        The checks, newest first.
    """
    rows = session.execute(
        sa.select(models.CheckDefinitionRow).order_by(models.CheckDefinitionRow.id.desc())
    ).scalars()
    return [
        wire.CheckOut(
            id=row.id,
            name=row.name,
            version=row.version,
            kind=row.kind,  # type: ignore[arg-type]
            expression=row.expression,
            instruction=row.instruction,
            reasoning=row.reasoning,
            severity=row.severity,  # type: ignore[arg-type]
            scope=row.scope,
            is_active=row.is_active,
            created_at=row.created_at,
            references=sorted(_safe_references(row.expression)),
        )
        for row in rows
    ]


@router.post("/checks", response_model=wire.CheckOut, status_code=status.HTTP_201_CREATED)
def save_check(
    payload: wire.CheckIn,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> wire.CheckOut:
    """Create a check, or save a new version of an existing one.

    Editing bumps the version rather than overwriting, so a finding can always say which
    version of which check produced it (``docs/design.md`` "Configurable checks").

    Args:
        payload: The check.
        session: The request's session.
        user: The caller.

    Returns:
        The stored check.

    Raises:
        HTTPException: 422 when an expression check has no valid expression, or a
            judgment check has no instruction.
    """
    require_admin(user)

    if payload.kind == "expression":
        if not payload.expression.strip():
            raise HTTPException(HTTP_422, "an expression check needs an expression")
        try:
            validate(payload.expression)
        except ExpressionError as exc:
            raise HTTPException(HTTP_422, str(exc)) from exc
    elif not payload.instruction.strip():
        raise HTTPException(HTTP_422, "a judgment check needs an instruction")

    existing = session.execute(
        sa.select(models.CheckDefinitionRow)
        .where(models.CheckDefinitionRow.name == payload.name)
        .order_by(models.CheckDefinitionRow.version.desc())
        .limit(1)
    ).scalar_one_or_none()

    row = models.CheckDefinitionRow(
        name=payload.name,
        version=(existing.version + 1) if existing else 1,
        kind=payload.kind,
        expression=payload.expression,
        instruction=payload.instruction,
        reasoning=payload.reasoning,
        severity=payload.severity,
        scope=payload.scope,
        is_active=payload.is_active,
    )
    if existing is not None:
        # Only one version of a check is active at a time; the older rows stay for
        # provenance.
        existing.is_active = False
    session.add(row)
    session.flush()

    repository.audit(session, "admin.check_saved", detail=f"{payload.name} v{row.version}")
    return wire.CheckOut(
        id=row.id,
        version=row.version,
        created_at=row.created_at,
        references=sorted(_safe_references(row.expression)),
        **payload.model_dump(),
    )


@router.patch("/checks/{check_id}/active", response_model=wire.CheckOut)
def set_check_active(
    check_id: int,
    is_active: bool,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> wire.CheckOut:
    """Enable or disable a check without touching old findings.

    Disabling removes it from new runs. Findings it already produced keep their check
    version, so an earlier report still explains itself.

    Args:
        check_id: The row id.
        is_active: Whether the check should run.
        session: The request's session.
        user: The caller.

    Returns:
        The updated check.

    Raises:
        HTTPException: 404 when it does not exist.
    """
    require_admin(user)
    row = session.get(models.CheckDefinitionRow, check_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"check {check_id} not found")
    row.is_active = is_active
    repository.audit(
        session, "admin.check_toggled", detail=f"{row.name} {'on' if is_active else 'off'}"
    )
    return wire.CheckOut(
        id=row.id,
        name=row.name,
        version=row.version,
        kind=row.kind,  # type: ignore[arg-type]
        expression=row.expression,
        instruction=row.instruction,
        reasoning=row.reasoning,
        severity=row.severity,  # type: ignore[arg-type]
        scope=row.scope,
        is_active=row.is_active,
        created_at=row.created_at,
        references=sorted(_safe_references(row.expression)),
    )


@router.post("/checks/draft", response_model=wire.DraftResponse)
def draft_check(
    payload: wire.DraftRequest,
    request: Request,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> wire.DraftResponse:
    """Propose named values and an expression from a plain-English description.

    **The only LLM call in the admin flow**, and it happens once per check. The result
    is cached like every other call (ADR-005), so re-opening the dialog with the same
    description costs nothing.

    Args:
        payload: The description and the report types available.
        request: The incoming request.
        session: The request's session.
        user: The caller.

    Returns:
        The proposal, with warnings for anything an admin should look at.

    Raises:
        HTTPException: 502 when the model cannot be reached or its answer does not
            validate after the single retry.
    """
    require_admin(user)

    available = payload.report_types or catalog.active_report_keys(session) or sorted(PARSERS)

    settings = request.app.state.llm_settings
    client = build_client(
        settings,
        cache=LLMCache(
            backend=request.app.state.llm_cache_backend,
            model=settings.model,
            prompt_version=settings.prompt_version,
        ),
    )

    try:
        result = client.complete(
            DRAFT_CHECK_PROMPT.system,
            DRAFT_CHECK_PROMPT.render(
                description=payload.description, report_types=", ".join(available)
            ),
            DRAFT_CHECK_PROMPT.schema,
            stage="admin_draft_check",
            prompt_version=DRAFT_CHECK_PROMPT.version,
        )
        drafted = result.parsed(DraftCheckResponse)
    except LLMError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"the model could not draft this check: {exc}"
        ) from exc

    warnings: list[str] = []
    try:
        referenced = validate(drafted.expression)
    except ExpressionError as exc:
        referenced = frozenset()
        warnings.append(f"The proposed expression is not valid: {exc}")

    proposed = {value.name for value in drafted.named_values}
    for name in sorted(referenced - proposed):
        warnings.append(f"The expression uses {name!r}, which the proposal does not define.")
    known = set(catalog.active_report_keys(session)) | set(PARSERS)
    for value in drafted.named_values:
        if value.report_type not in known:
            warnings.append(f"{value.name}: {value.report_type!r} is not a known report type.")

    # A model that invents a severity outside the set gets the safe default rather than
    # failing the whole draft; the admin sees and corrects it either way.
    severity: Any = drafted.severity if drafted.severity in ("high", "medium", "low") else "medium"

    repository.audit(session, "admin.check_drafted", detail=payload.description[:120])
    return wire.DraftResponse(
        named_values=[
            wire.NamedValueIn(
                name=value.name,
                report_type=value.report_type,
                sheet=value.sheet,
                kind="cell" if value.kind == "cell" else "label",
                cell=value.cell,
                label=value.label,
                label_column=value.label_column,
                value_column=value.value_column,
                description=value.description,
            )
            for value in drafted.named_values
        ],
        expression=drafted.expression,
        reasoning=drafted.reasoning,
        severity=severity,
        cached=result.cached,
        warnings=warnings,
    )


@router.post("/checks/test", response_model=wire.TestResult)
def test_expression(
    payload: wire.TestRequest,
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    user: CurrentUser = Depends(current_user),
) -> wire.TestResult:
    """Evaluate an expression against the uploaded sample workbooks.

    No LLM call: this is the same evaluator the worker uses, so a check that passes here
    behaves the same way on a real run.

    Args:
        payload: The expression.
        session: The request's session.
        data_dir: The shared volume.
        user: The caller.

    Returns:
        The outcome, naming any value that could not be resolved.
    """
    require_admin(user)
    documents = _load_templates(session, data_dir)
    rows = list(session.execute(sa.select(models.NamedValueRow)).scalars())

    values: dict[str, Any] = {}
    unresolved: list[str] = []
    for row in rows:
        raw = resolve(_to_named_value(row), documents)
        number = to_number(raw)
        values[row.name] = number if number is not None else raw
        if raw is None:
            unresolved.append(row.name)

    try:
        outcome = evaluate(payload.expression, values)
    except UnresolvedValue as exc:
        return wire.TestResult(
            passed=None,
            detail=(
                f"{exc.name!r} could not be resolved against the uploaded samples. "
                "On a real run this becomes a 'could not evaluate' finding, never a "
                "silent skip."
            ),
            resolved={k: v for k, v in values.items() if v is not None},
            unresolved=sorted({*unresolved, exc.name}),
        )
    except ExpressionError as exc:
        return wire.TestResult(passed=None, detail=str(exc), unresolved=unresolved)

    inputs = ", ".join(f"{name} = {value}" for name, value in sorted(outcome.resolved.items()))
    return wire.TestResult(
        passed=outcome.passed,
        detail=f"{payload.expression} → {outcome.passed} with {inputs}",
        resolved=dict(outcome.resolved),
        unresolved=unresolved,
    )


# ------------------------------------------------------- compliance and scope


@router.get("/compliance-rules", response_model=list[wire.ComplianceRuleOut])
def list_compliance_rules(
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> list[wire.ComplianceRuleOut]:
    """List the must-have compliance rules.

    Args:
        session: The request's session.
        _user: The caller.

    Returns:
        The rules.
    """
    rows = session.execute(
        sa.select(models.ComplianceRuleRow).order_by(models.ComplianceRuleRow.name)
    ).scalars()
    return [
        wire.ComplianceRuleOut(
            id=row.id,
            name=row.name,
            json_path_contains=str((row.requirement or {}).get("json_path_contains", "")),
            expected_value=(row.requirement or {}).get("expected_value", True),
            scope=row.scope,
            reasoning=row.reasoning,
            is_active=row.is_active,
        )
        for row in rows
    ]


@router.post(
    "/compliance-rules", response_model=wire.ComplianceRuleOut, status_code=status.HTTP_201_CREATED
)
def save_compliance_rule(
    payload: wire.ComplianceRuleIn,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> wire.ComplianceRuleOut:
    """Create or replace a compliance rule.

    Args:
        payload: The rule.
        session: The request's session.
        user: The caller.

    Returns:
        The stored rule.
    """
    require_admin(user)
    row = session.execute(
        sa.select(models.ComplianceRuleRow).where(models.ComplianceRuleRow.name == payload.name)
    ).scalar_one_or_none()
    if row is None:
        row = models.ComplianceRuleRow(name=payload.name)
        session.add(row)
    row.requirement = {
        "json_path_contains": payload.json_path_contains,
        "expected_value": payload.expected_value,
    }
    row.scope = payload.scope
    row.reasoning = payload.reasoning
    row.is_active = payload.is_active
    session.flush()
    repository.audit(session, "admin.compliance_saved", detail=payload.name)
    return wire.ComplianceRuleOut(id=row.id, **payload.model_dump())


@router.delete("/compliance-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_compliance_rule(
    rule_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> None:
    """Delete a compliance rule.

    Args:
        rule_id: The row id.
        session: The request's session.
        user: The caller.

    Raises:
        HTTPException: 404 when it does not exist.
    """
    require_admin(user)
    row = session.get(models.ComplianceRuleRow, rule_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"compliance rule {rule_id} not found")
    session.delete(row)
    repository.audit(session, "admin.compliance_deleted", detail=row.name)


@router.get("/categories", response_model=list[wire.CategoryOut])
def list_categories(
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> list[wire.CategoryOut]:
    """List the reverse-pass categories.

    Args:
        session: The request's session.
        _user: The caller.

    Returns:
        The stored categories, or the shipped defaults when none are configured. An
        empty table must not silently mean "check nothing".
    """
    rows = list(session.execute(sa.select(models.ReversePassCategoryRow)).scalars())
    if rows:
        return [
            wire.CategoryOut(
                id=row.id, name=row.name, kinds=list(row.kinds or []), checked=row.checked
            )
            for row in rows
        ]
    from greenlight_ai.checks.definitions import DEFAULT_CATEGORIES

    return [
        wire.CategoryOut(
            id=0, name=category.name, kinds=list(category.kinds), checked=category.checked
        )
        for category in DEFAULT_CATEGORIES
    ]


@router.post("/categories", response_model=wire.CategoryOut, status_code=status.HTTP_201_CREATED)
def save_category(
    payload: wire.CategoryIn,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> wire.CategoryOut:
    """Create or replace a reverse-pass category.

    Saving the first one takes the defaults out of play, so the shipped list is seeded
    into the table first. Otherwise switching one category off would silently enable
    every other default.

    Args:
        payload: The category.
        session: The request's session.
        user: The caller.

    Returns:
        The stored category.
    """
    require_admin(user)
    existing = list(session.execute(sa.select(models.ReversePassCategoryRow)).scalars())
    if not existing:
        from greenlight_ai.checks.definitions import DEFAULT_CATEGORIES

        for default in DEFAULT_CATEGORIES:
            session.add(
                models.ReversePassCategoryRow(
                    name=default.name, kinds=list(default.kinds), checked=default.checked
                )
            )
        session.flush()

    row = session.execute(
        sa.select(models.ReversePassCategoryRow).where(
            models.ReversePassCategoryRow.name == payload.name
        )
    ).scalar_one_or_none()
    if row is None:
        row = models.ReversePassCategoryRow(name=payload.name)
        session.add(row)
    row.kinds = list(payload.kinds)
    row.checked = payload.checked
    session.flush()
    repository.audit(session, "admin.category_saved", detail=payload.name)
    return wire.CategoryOut(id=row.id, **payload.model_dump())


# ------------------------------------------------------------------ reference data


@router.get("/aliases", response_model=list[wire.AliasOut])
def list_aliases(
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> list[wire.AliasOut]:
    """List the attribute aliases.

    Args:
        session: The request's session.
        _user: The caller.

    Returns:
        The aliases, grouped by canonical name in the UI.
    """
    rows = session.execute(
        sa.select(models.AttributeAlias).order_by(
            models.AttributeAlias.canonical_name, models.AttributeAlias.alias
        )
    ).scalars()
    return [
        wire.AliasOut(
            id=row.id,
            canonical_name=row.canonical_name,
            alias=row.alias,
            customer_name=row.customer_name,
        )
        for row in rows
    ]


@router.post("/aliases", response_model=wire.AliasOut, status_code=status.HTTP_201_CREATED)
def create_alias(
    payload: wire.AliasIn,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> wire.AliasOut:
    """Add an attribute alias.

    Args:
        payload: The alias.
        session: The request's session.
        user: The caller.

    Returns:
        The stored alias.
    """
    require_admin(user)
    row = models.AttributeAlias(
        canonical_name=payload.canonical_name.strip(),
        alias=payload.alias.strip(),
        customer_name=payload.customer_name,
    )
    session.add(row)
    session.flush()
    repository.audit(
        session, "admin.alias_added", detail=f"{payload.alias}→{payload.canonical_name}"
    )
    return wire.AliasOut(id=row.id, **payload.model_dump())


@router.delete("/aliases/{alias_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_alias(
    alias_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> None:
    """Delete an attribute alias.

    Args:
        alias_id: The row id.
        session: The request's session.
        user: The caller.

    Raises:
        HTTPException: 404 when it does not exist.
    """
    require_admin(user)
    row = session.get(models.AttributeAlias, alias_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"alias {alias_id} not found")
    session.delete(row)
    repository.audit(session, "admin.alias_deleted", detail=row.alias)


@router.get("/masked-columns", response_model=list[wire.MaskedColumnOut])
def list_masked_columns(
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> list[wire.MaskedColumnOut]:
    """List the masked-column patterns.

    Args:
        session: The request's session.
        _user: The caller.

    Returns:
        The configured patterns, or the shipped defaults when none are configured. An
        empty table must never mean "mask nothing" (ADR-003), so the defaults are shown
        as such rather than as an empty list.
    """
    rows = list(
        session.execute(
            sa.select(models.MaskedColumn).order_by(models.MaskedColumn.pattern)
        ).scalars()
    )
    if rows:
        return [
            wire.MaskedColumnOut(id=row.id, pattern=row.pattern, description=row.description)
            for row in rows
        ]
    return [
        wire.MaskedColumnOut(id=0, pattern=pattern, description="Shipped default", is_default=True)
        for pattern in DEFAULT_MASKED_COLUMNS
    ]


@router.post(
    "/masked-columns", response_model=wire.MaskedColumnOut, status_code=status.HTTP_201_CREATED
)
def create_masked_column(
    payload: wire.MaskedColumnIn,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> wire.MaskedColumnOut:
    """Add a masked-column pattern.

    The first one added seeds the shipped defaults alongside it, so adding one pattern
    can never accidentally unmask everything else (ADR-003).

    Args:
        payload: The pattern.
        session: The request's session.
        user: The caller.

    Returns:
        The stored pattern.
    """
    require_admin(user)
    if not session.execute(sa.select(models.MaskedColumn).limit(1)).scalar_one_or_none():
        for default in DEFAULT_MASKED_COLUMNS:
            session.add(models.MaskedColumn(pattern=default, description="Shipped default"))
        session.flush()

    existing = session.execute(
        sa.select(models.MaskedColumn).where(models.MaskedColumn.pattern == payload.pattern)
    ).scalar_one_or_none()
    if existing is not None:
        return wire.MaskedColumnOut(
            id=existing.id, pattern=existing.pattern, description=existing.description
        )

    row = models.MaskedColumn(pattern=payload.pattern, description=payload.description)
    session.add(row)
    session.flush()
    repository.audit(session, "admin.masked_column_added", detail=payload.pattern)
    return wire.MaskedColumnOut(id=row.id, **payload.model_dump())


@router.delete("/masked-columns/{column_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_masked_column(
    column_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> None:
    """Remove a masked-column pattern.

    Args:
        column_id: The row id.
        session: The request's session.
        user: The caller.

    Raises:
        HTTPException: 404 when it does not exist.
    """
    require_admin(user)
    row = session.get(models.MaskedColumn, column_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"masked column {column_id} not found")
    session.delete(row)
    repository.audit(session, "admin.masked_column_deleted", detail=row.pattern)


# --------------------------------------------------------------------------- usage


def _percentile(values: Sequence[int], fraction: float) -> int:
    """Return a percentile without pulling in a statistics dependency.

    Args:
        values: The samples.
        fraction: The percentile, 0 to 1.

    Returns:
        The value at that percentile, or 0 when there are no samples.
    """
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


@router.get("/usage", response_model=wire.UsageOut)
def usage(
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> wire.UsageOut:
    """Report the numbers on the admin dashboard.

    Plain SQL over `runs`, `run_stages`, `llm_calls`, and `findings`
    (``docs/phase-4.md``). No LLM call and no derived tables to keep in step.

    Args:
        session: The request's session.
        _user: The caller.

    Returns:
        The usage numbers.
    """
    runs = list(session.execute(sa.select(models.Run)).scalars())
    finished = [r for r in runs if r.status in ("needs_review", "finalized")]
    failed = [r for r in runs if r.status == "failed"]

    durations = [
        int(
            session.execute(
                sa.select(sa.func.coalesce(sa.func.sum(models.RunStage.duration_ms), 0)).where(
                    models.RunStage.run_id == run.id
                )
            ).scalar_one()
        )
        for run in finished
    ]

    runs_per_day: dict[str, int] = {}
    for run in runs:
        runs_per_day[run.created_at.date().isoformat()] = (
            runs_per_day.get(run.created_at.date().isoformat(), 0) + 1
        )

    calls = list(session.execute(sa.select(models.LlmCall)).scalars())
    tokens_per_day: dict[str, int] = {}
    for call in calls:
        key = call.created_at.date().isoformat()
        tokens_per_day[key] = (
            tokens_per_day.get(key, 0) + call.prompt_tokens + call.completion_tokens
        )

    findings = list(session.execute(sa.select(models.Finding)).scalars())
    by_type: dict[str, int] = {}
    for finding in findings:
        by_type[finding.type] = by_type.get(finding.type, 0) + 1

    decisions: dict[str, int] = {}
    for finding in findings:
        decisions[finding.review_status] = decisions.get(finding.review_status, 0) + 1

    decided = sum(count for status_, count in decisions.items() if status_ != "undecided")
    false_positives = decisions.get("false_positive", 0)

    return wire.UsageOut(
        runs_total=len(runs),
        runs_per_day=[wire.DayCount(day=d, count=c) for d, c in sorted(runs_per_day.items())],
        duration_p50_ms=_percentile(durations, 0.5),
        duration_p95_ms=_percentile(durations, 0.95),
        failure_rate=round(len(failed) / len(runs), 4) if runs else 0.0,
        tokens_total=sum(c.prompt_tokens + c.completion_tokens for c in calls),
        tokens_per_day=[wire.DayCount(day=d, count=c) for d, c in sorted(tokens_per_day.items())],
        cache_hit_rate=round(sum(1 for c in calls if c.cached) / len(calls), 4) if calls else 0.0,
        json_failure_rate=(
            round(sum(1 for c in calls if not c.ok) / len(calls), 4) if calls else 0.0
        ),
        false_positive_rate=round(false_positives / decided, 4) if decided else 0.0,
        findings_by_type=by_type,
        decisions=decisions,
    )


# ------------------------------------------------------------- programme rules


def _programme_rule_out(row: models.ProgrammeRule) -> wire.ProgrammeRuleOut:
    """Render a programme rule.

    Args:
        row: The stored rule.

    Returns:
        The wire model.
    """
    return wire.ProgrammeRuleOut(
        id=row.id,
        scope_code=row.scope_code,
        title=row.title,
        text=row.text,
        strictness=row.strictness,  # type: ignore[arg-type]
        sort_order=row.sort_order,
        state=row.state,
        origin=row.origin,
        created_by=row.created_by,
    )


@router.get("/programme-rules", response_model=list[wire.ProgrammeRuleOut])
def list_programme_rules(
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
    scope_code: str | None = Query(default=None),
) -> list[wire.ProgrammeRuleOut]:
    """The rules true of every delivery in a programme (ADR-026).

    Args:
        session: The request's session.
        _user: The caller.
        scope_code: One programme, or every programme when omitted.

    Returns:
        The rules in display order, every state except deleted.
    """
    statement = (
        sa.select(models.ProgrammeRule)
        .where(models.ProgrammeRule.state != "deleted")
        .order_by(
            models.ProgrammeRule.scope_code,
            models.ProgrammeRule.sort_order,
            models.ProgrammeRule.id,
        )
    )
    if scope_code:
        statement = statement.where(models.ProgrammeRule.scope_code == scope_code.strip().upper())
    return [_programme_rule_out(row) for row in session.execute(statement).scalars()]


@router.post(
    "/programme-rules", response_model=wire.ProgrammeRuleOut, status_code=status.HTTP_201_CREATED
)
def create_programme_rule(
    payload: wire.ProgrammeRuleIn,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> wire.ProgrammeRuleOut:
    """Add a rule to a programme.

    The model reads for breaches of it; the strictness decides how serious a breach
    is, and code applies that, so the model never grades.

    Args:
        payload: The rule.
        session: The request's session.
        user: The calling administrator.

    Returns:
        The stored rule, active at once.

    Raises:
        HTTPException: 404 when the programme does not exist.
    """
    require_admin(user)
    catalog.seed_defaults(session)
    code = payload.scope_code.strip().upper()
    if catalog.scope_for(session, code) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no programme {code!r}")
    row = models.ProgrammeRule(
        scope_code=code,
        title=payload.title.strip(),
        text=payload.text.strip(),
        strictness=payload.strictness,
        sort_order=payload.sort_order,
        scope=f"programme:{code}",
        created_by=user.name,
    )
    session.add(row)
    session.flush()
    repository.audit(
        session,
        "admin.programme_rule_created",
        detail=f"{code}:{row.id}",
        user_id=user.id,
        actor=user.name,
    )
    versions.record_programme_version(session, code, user.name, f"rule added: {row.title}")
    return _programme_rule_out(row)


@router.patch("/programme-rules/{rule_id}", response_model=wire.ProgrammeRuleOut)
def edit_programme_rule(
    rule_id: int,
    payload: wire.ProgrammeRuleIn,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> wire.ProgrammeRuleOut:
    """Reword a programme rule or change its strictness.

    Args:
        rule_id: The rule.
        payload: The new wording.
        session: The request's session.
        user: The calling administrator.

    Returns:
        The updated rule. Its state is changed on the Rules screen, not here.

    Raises:
        HTTPException: 404 when it does not exist.
    """
    require_admin(user)
    row = session.get(models.ProgrammeRule, rule_id)
    if row is None or row.state == "deleted":
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no programme rule {rule_id}")
    row.title = payload.title.strip()
    row.text = payload.text.strip()
    row.strictness = payload.strictness
    row.sort_order = payload.sort_order
    session.flush()
    repository.audit(
        session,
        "admin.programme_rule_edited",
        detail=str(rule_id),
        user_id=user.id,
        actor=user.name,
    )
    versions.record_programme_version(
        session, row.scope_code, user.name, f"rule edited: {row.title}"
    )
    return _programme_rule_out(row)


# ------------------------------------------------------------------- versions


_VERSION_KINDS: Final[dict[str, versions.VersionKind]] = {
    "artifact-type": "artifact_type",
    "programme": "programme_rules",
}


def _version_kind(kind: str) -> versions.VersionKind:
    try:
        return _VERSION_KINDS[kind]
    except KeyError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"no versioned definition kind {kind!r}"
        ) from None


def _version_out(row: models.DefinitionVersion) -> wire.VersionOut:
    return wire.VersionOut(
        version=row.version,
        summary=row.summary,
        reverted_from=row.reverted_from,
        created_by=row.created_by,
        created_at=row.created_at,
        snapshot=row.snapshot or {},
    )


@router.get("/versions/{kind}/{key}", response_model=list[wire.VersionOut])
def list_definition_versions(
    kind: str,
    key: str,
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(require_admin),
) -> list[wire.VersionOut]:
    """The last ten versions of an artifact type or a programme's rules, newest first.

    Args:
        kind: ``artifact-type`` or ``programme``.
        key: The artifact key or the programme code.
        session: The request's session.
        _user: The calling administrator.

    Returns:
        The versions, each with who, when, a one-line summary, and the snapshot.
    """
    return [_version_out(row) for row in versions.list_versions(session, _version_kind(kind), key)]


@router.post("/versions/{kind}/{key}/{version}/revert", response_model=wire.VersionOut)
def revert_definition_version(
    kind: str,
    key: str,
    version: int,
    payload: wire.RevertIn,
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    user: CurrentUser = Depends(require_admin),
) -> wire.VersionOut:
    """Put an old version back, as a new version (ADR-029).

    Args:
        kind: ``artifact-type`` or ``programme``.
        key: The artifact key or the programme code.
        version: The version to restore.
        payload: The typed confirmation.
        session: The request's session.
        data_dir: The shared volume, where sample workbooks live.
        user: The calling administrator.

    Returns:
        The new version carrying the restored state.

    Raises:
        HTTPException: 400 when the word was not typed, 404 when the version does not
            exist.
    """
    if payload.confirm.strip().lower() != "revert":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "type 'revert' to confirm; this applies to every future run",
        )
    try:
        row = versions.revert(session, _version_kind(kind), key, version, data_dir, user.name)
    except versions.VersionError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    repository.audit(
        session,
        "admin.definition_reverted",
        detail=f"{kind}:{key}:{version}",
        user_id=user.id,
        actor=user.name,
    )
    return _version_out(row)
