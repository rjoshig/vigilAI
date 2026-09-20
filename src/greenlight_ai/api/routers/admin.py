"""Admin endpoints: templates, named values, checks, compliance, reference data, usage.

Checks are defined as data, not code. The model helps write one *once*
(``POST /admin/checks/draft``); after that the check runs as code on every request at no
token cost (``docs/design.md`` "Configurable checks"). Testing a check never calls the
model.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Mapping, Sequence, cast

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

from greenlight_ai import announcements, scopes
from greenlight_ai.api import schemas_admin as wire
from greenlight_ai.api.deps import (
    DELETE_WORD,
    require_delete_word,
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
from greenlight_ai.checks import field_labels
from greenlight_ai.db.types import utcnow
from greenlight_ai.db import catalog, models, repository, versions
from greenlight_ai.training import lifecycle
from greenlight_ai.llm.cache import LLMCache
from greenlight_ai.llm.client import LLMError
from greenlight_ai.llm.factory import build_client
from greenlight_ai.llm import examples as example_library
from greenlight_ai.llm.prompts import DRAFT_CHECK_PROMPT, get_prompt
from greenlight_ai.llm.prompts.schemas import DraftCheckResponse
from greenlight_ai.llm.tripwire import PiiDetected, assert_clean
from greenlight_ai.parsers.base import ParseError, ReportKind
from greenlight_ai.parsers.config_json import JsonConfigParser
from greenlight_ai.parsers.osl import osl_parser_for
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


def _osl_preview(path: Path) -> list[wire.SheetPreview]:
    """An OSL as the console previews it: one "sheet" per section, a cell per line.

    Args:
        path: The stored ``.docx`` or ``.pdf``.

    Returns:
        Sections in order; paragraphs as ``¶n`` and table rows as ``Tn rm``, so an
        administrator can point at the clause they mean.
    """
    document = osl_parser_for(path).parse(path)
    sheets: list[wire.SheetPreview] = []
    for section in document.sections:
        cells = [
            wire.CellPreview(cell=f"¶{i}", value=text[:200], label="", row=i, column=1)
            for i, text in enumerate(section.paragraphs, start=1)
        ]
        for table in section.tables:
            for r, row in enumerate(table.rows, start=1):
                cells.append(
                    wire.CellPreview(
                        cell=f"T{table.index} r{r}",
                        value=" | ".join(row)[:200],
                        label=" | ".join(table.header)[:200],
                        row=r,
                        column=1,
                    )
                )
        sheets.append(
            wire.SheetPreview(
                name=f"{section.number} {section.heading}"[:100],
                rows=len(cells),
                columns=1,
                cells=cells[:PREVIEW_CELLS],
            )
        )
    return sheets


def _config_preview(path: Path) -> list[wire.SheetPreview]:
    """An ETL configuration as the console previews it: one cell per block.

    Args:
        path: The stored ``.json``.

    Returns:
        One "sheet", the JSON path of each block as the cell and its content as the
        value, so a guide or a compliance rule can name the path it means.
    """
    document = JsonConfigParser().parse(path)
    cells = [
        wire.CellPreview(
            cell=block.json_path,
            value=json.dumps(block.content, sort_keys=True)[:200],
            label=block.kind,
            row=i,
            column=1,
        )
        for i, block in enumerate(document.blocks, start=1)
    ]
    return [
        wire.SheetPreview(
            name=f"Configuration {document.configuration_id}"[:100],
            rows=len(cells),
            columns=1,
            cells=cells[:PREVIEW_CELLS],
        )
    ]


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
    row: models.ArtifactType, data_dir: Path, in_use: int = 0, version: int = 0
) -> wire.ArtifactTypeOut:
    """Build the wire model for one artifact type.

    Args:
        row: The stored type.
        data_dir: The shared volume.
        in_use: How many runs have uploaded this type.
        version: Its newest definition version (ADR-029).

    Returns:
        The wire model, including the sample's sheets when there is one.
    """
    samples = [
        wire.SampleOut(
            id=sample.id,
            label=sample.label,
            scope_code=sample.scope_code or "",
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
        version=version,
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
    latest = versions.current_versions(session)
    return [
        _artifact_out(
            row, data_dir, counts.get(row.key, 0), latest.get(f"artifact_type:{row.key}", 0)
        )
        for row in rows
    ]


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
    return _artifact_out(
        row, data_dir, version=versions.latest_version(session, "artifact_type", row.key)
    )


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
    scope_code: Annotated[str, Form()] = "",
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    user: CurrentUser = Depends(require_admin),
) -> wire.ArtifactTypeOut:
    """Add a sample to an artifact type, up to three per delivery programme.

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
    scope = scope_code.strip().upper()
    if scope and catalog.scope_for(session, scope) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no programme {scope!r}")
    in_scope = [sample for sample in row.samples if (sample.scope_code or "") == scope]
    if len(in_scope) >= MAX_SAMPLES:
        where = f"for programme {scope}" if scope else "as global samples"
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{key!r} already has {MAX_SAMPLES} samples {where}; remove one before adding another",
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
        scope_code=scope,
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
    return _artifact_out(
        row, data_dir, version=versions.latest_version(session, "artifact_type", row.key)
    )


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
    return _artifact_out(
        row, data_dir, version=versions.latest_version(session, "artifact_type", row.key)
    )


@router.patch("/artifact-types/{key}/samples/{sample_id}", response_model=wire.ArtifactTypeOut)
def edit_sample(
    key: str,
    sample_id: int,
    payload: wire.SamplePatch,
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    user: CurrentUser = Depends(require_admin),
) -> wire.ArtifactTypeOut:
    """Relabel a sample, write notes on it, or move it to another programme.

    Notes reach the mapping interview as the administrator's words about that
    sample, so they are the place to say how this variant differs.

    Args:
        key: The artifact key.
        sample_id: The sample.
        payload: What changes.
        session: The request's session.
        data_dir: The shared volume.
        user: The calling administrator.

    Returns:
        The type with all of its samples.

    Raises:
        HTTPException: 404 for an unknown sample or programme, 409 when the target
            programme already has three samples of this type.
    """
    sample = _get_sample(session, key, sample_id)
    row = sample.artifact_type
    if payload.scope_code is not None:
        scope = payload.scope_code.strip().upper()
        if scope and catalog.scope_for(session, scope) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no programme {scope!r}")
        if scope != (sample.scope_code or ""):
            there = [s for s in row.samples if (s.scope_code or "") == scope and s.id != sample.id]
            if len(there) >= MAX_SAMPLES:
                where = f"programme {scope}" if scope else "the global samples"
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"{where} already has {MAX_SAMPLES} samples of {key!r}",
                )
            sample.scope_code = scope
    if payload.label is not None:
        sample.label = payload.label.strip()
    if payload.notes is not None:
        sample.notes = payload.notes.strip()
    session.flush()
    repository.audit(
        session,
        "admin.sample_edited",
        detail=f"{key}/{sample_id}",
        user_id=user.id,
        actor=user.name,
    )
    versions.record_artifact_version(session, row, user.name, "sample edited")
    return _artifact_out(
        row, data_dir, version=versions.latest_version(session, "artifact_type", row.key)
    )


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
    kind = sample.artifact_type.kind
    try:
        if kind == "osl":
            sheets = _osl_preview(path)
        elif kind == "config":
            sheets = _config_preview(path)
        else:
            masked = repository.load_masked_columns(session)
            sheets = [_sheet_preview(sheet, masked) for sheet in parser_for(key).parse(path).sheets]
    except ParseError as exc:
        raise HTTPException(HTTP_422, f"the sample could not be read: {exc}") from exc

    return wire.SamplePreviewOut(sample_id=sample.id, filename=sample.filename, sheets=sheets)


@router.delete("/artifact-types/{key}/samples/{sample_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sample(
    key: str,
    sample_id: int,
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    user: CurrentUser = Depends(require_admin),
    _confirmed: None = Depends(require_delete_word),
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
    _confirmed: None = Depends(require_delete_word),
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
    latest = versions.current_versions(session)
    return [
        wire.ScopeOut(
            id=row.id,
            code=row.code,
            label=row.label,
            description=row.description,
            standing_instructions=row.standing_instructions,
            is_active=row.is_active,
            sort_order=row.sort_order,
            second_approver=row.second_approver,
            keywords=list(row.keywords or []),
            runs_using=counts.get(row.code, 0),
            version=latest.get(f"programme_rules:{row.code}", 0),
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
    row.second_approver = payload.second_approver
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
        second_approver=row.second_approver,
        keywords=list(row.keywords or []),
        version=versions.latest_version(session, "programme_rules", row.code),
    )


@router.delete("/scopes/{code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scope(
    code: str,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
    _confirmed: None = Depends(require_delete_word),
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
    _confirmed: None = Depends(require_delete_word),
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
        sa.select(models.CheckDefinitionRow)
        .where(models.CheckDefinitionRow.state != "deleted")
        .order_by(models.CheckDefinitionRow.id.desc())
    ).scalars()
    return [
        wire.CheckOut(
            id=row.id,
            name=row.name,
            version=row.version,
            kind=row.kind,  # type: ignore[arg-type]
            expression=row.expression,
            instruction=row.instruction,
            value_names=list(row.value_names or []),
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
            judgment check has no instruction or names no values.
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
    elif not [name for name in payload.value_names if name.strip()]:
        raise HTTPException(
            HTTP_422, "a judgment check needs at least one named value the model may see"
        )

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
        value_names=list(payload.value_names),
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
        value_names=list(row.value_names or []),
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


def _compliance_out(row: models.ComplianceRuleRow) -> wire.ComplianceRuleOut:
    """Build the wire model for one compliance rule."""
    return wire.ComplianceRuleOut(
        id=row.id,
        name=row.name,
        json_path_contains=str((row.requirement or {}).get("json_path_contains", "")),
        expected_value=(row.requirement or {}).get("expected_value", True),
        scope=row.scope,
        reasoning=row.reasoning,
        is_active=row.is_active,
        version=row.version or 1,
    )


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
        sa.select(models.ComplianceRuleRow)
        .where(models.ComplianceRuleRow.state != "deleted")
        .order_by(models.ComplianceRuleRow.name)
    ).scalars()
    return [_compliance_out(row) for row in rows]


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
    return _compliance_out(row)


@router.delete("/compliance-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_compliance_rule(
    rule_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
    _confirmed: None = Depends(require_delete_word),
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


def _announcement_out(row: models.Announcement, now: Any = None) -> wire.AnnouncementOut:
    """Render one notice for the console.

    Args:
        row: The stored row.
        now: The moment to judge "showing" against; the real one when omitted.

    Returns:
        The wire model, saying whether it is showing at this moment so nobody has to
        compare dates in their head.
    """
    moment = now or utcnow()
    return wire.AnnouncementOut(
        id=row.id,
        level=row.level,
        audience=row.audience,
        message=row.message,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        is_active=row.is_active,
        created_by=row.created_by,
        showing_now=bool(row.is_active and row.starts_at <= moment < row.ends_at),
    )


@router.get("/announcements", response_model=list[wire.AnnouncementOut])
def list_announcements(
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> list[wire.AnnouncementOut]:
    """Every scheduled notice, soonest first.

    Args:
        session: The request's session.
        _user: The caller.

    Returns:
        The notices, including expired ones, which are kept so a recurring message can
        be switched back on rather than retyped.
    """
    rows = session.execute(
        sa.select(models.Announcement).order_by(models.Announcement.starts_at.desc())
    ).scalars()
    return [_announcement_out(row) for row in rows]


@router.post(
    "/announcements", response_model=wire.AnnouncementOut, status_code=status.HTTP_201_CREATED
)
def create_announcement(
    payload: wire.AnnouncementIn,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> wire.AnnouncementOut:
    """Schedule a notice.

    Args:
        payload: The message, its level, its audience and its window.
        session: The request's session.
        user: The caller, recorded against the row.

    Returns:
        The stored notice.

    Raises:
        HTTPException: 422 with the reason when it cannot be scheduled as written.
    """
    require_admin(user)
    try:
        announcements.validate(
            session,
            payload.message,
            payload.level,
            payload.audience,
            payload.starts_at,
            payload.ends_at,
        )
    except announcements.AnnouncementError as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc

    row = models.Announcement(
        level=payload.level,
        audience=payload.audience,
        message=payload.message.strip(),
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        is_active=payload.is_active,
        created_by=user.name,
        created_by_user_id=user.id,
    )
    session.add(row)
    session.flush()
    repository.audit(
        session,
        "admin.announcement_scheduled",
        detail=f"{payload.level}/{payload.audience} until {payload.ends_at:%Y-%m-%d %H:%M}",
        user_id=user.id,
        actor=user.name,
    )
    return _announcement_out(row)


@router.post("/announcements/{announcement_id}/active", response_model=wire.AnnouncementOut)
def set_announcement_active(
    announcement_id: int,
    active: bool = Query(...),
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> wire.AnnouncementOut:
    """Switch a notice on or off without losing it.

    Args:
        announcement_id: The row id.
        active: Whether it should show inside its window.
        session: The request's session.
        user: The caller.

    Returns:
        The updated notice.

    Raises:
        HTTPException: 404 when it does not exist, 422 when switching it back on
            would exceed the limit.
    """
    require_admin(user)
    row = session.get(models.Announcement, announcement_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"notice {announcement_id} not found")
    if active and not row.is_active:
        try:
            announcements.validate(
                session,
                row.message,
                row.level,
                row.audience,
                row.starts_at,
                row.ends_at,
                exclude_id=row.id,
            )
        except announcements.AnnouncementError as exc:
            raise HTTPException(HTTP_422, str(exc)) from exc
    row.is_active = active
    repository.audit(
        session,
        "admin.announcement_on" if active else "admin.announcement_off",
        detail=row.message[:80],
        user_id=user.id,
        actor=user.name,
    )
    return _announcement_out(row)


@router.delete("/announcements/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_announcement(
    announcement_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
    _confirmed: None = Depends(require_delete_word),
) -> None:
    """Delete a notice.

    Args:
        announcement_id: The row id.
        session: The request's session.
        user: The caller.

    Raises:
        HTTPException: 404 when it does not exist.
    """
    require_admin(user)
    row = session.get(models.Announcement, announcement_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"notice {announcement_id} not found")
    session.delete(row)
    repository.audit(
        session,
        "admin.announcement_deleted",
        detail=row.message[:80],
        user_id=user.id,
        actor=user.name,
    )


@router.get("/field-labels", response_model=list[wire.FieldLabelOut])
def list_field_labels(
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> list[wire.FieldLabelOut]:
    """List what deliveries call the fields the tool checks (Phase 6.14b).

    The built-in spellings are listed first and read-only, so an administrator can see
    what is already covered before adding one. They are not rows in the table: a
    deployment that configures nothing still checks with them.

    Args:
        session: The request's session.
        _user: The caller.

    Returns:
        The built-ins, then the configured labels.
    """
    out: list[wire.FieldLabelOut] = [
        wire.FieldLabelOut(
            id=0,
            canonical=canonical,
            label=label,
            scope=scopes.EVERYWHERE,
            scope_label="Everywhere",
            is_active=True,
            is_builtin=True,
        )
        for canonical, labels in field_labels.DEFAULT_LABELS.items()
        for label in labels
    ]
    rows = session.execute(
        sa.select(models.FieldLabel).order_by(models.FieldLabel.canonical, models.FieldLabel.id)
    ).scalars()
    out.extend(
        wire.FieldLabelOut(
            id=row.id,
            canonical=row.canonical,
            label=row.label,
            scope=row.scope,
            scope_label=scopes.label(row.scope),
            is_active=row.is_active,
            created_by=row.created_by,
        )
        for row in rows
    )
    return out


@router.post(
    "/field-labels", response_model=wire.FieldLabelOut, status_code=status.HTTP_201_CREATED
)
def create_field_label(
    payload: wire.FieldLabelIn,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> wire.FieldLabelOut:
    """Add a label for a field the tool checks.

    Args:
        payload: The label and where it applies.
        session: The request's session.
        user: The caller, recorded against the row.

    Returns:
        The stored label.

    Raises:
        HTTPException: 422 when the field is not one the tool checks, or the label
            duplicates one already in force for that scope.
    """
    require_admin(user)
    if payload.canonical not in field_labels.CANONICAL_FIELDS:
        raise HTTPException(
            HTTP_422,
            f"{payload.canonical!r} is not a field the tool checks; "
            f"it checks {', '.join(field_labels.CANONICAL_FIELDS)}",
        )
    scope = scopes.token(payload.scope)
    existing = session.execute(
        sa.select(models.FieldLabel).where(
            models.FieldLabel.canonical == payload.canonical,
            models.FieldLabel.scope == scope,
        )
    ).scalars()
    wanted = field_labels.normalize_label(payload.label)
    if any(field_labels.normalize_label(row.label) == wanted for row in existing):
        raise HTTPException(
            HTTP_422, f"{payload.label!r} is already a label for {payload.canonical} here"
        )

    row = models.FieldLabel(
        canonical=payload.canonical,
        label=payload.label.strip(),
        scope=scope,
        is_active=payload.is_active,
        created_by=user.name,
        created_by_user_id=user.id,
    )
    session.add(row)
    session.flush()
    repository.audit(
        session,
        "admin.field_label_added",
        detail=f"{payload.canonical}:{payload.label} @ {scope}",
        user_id=user.id,
        actor=user.name,
    )
    versions.record_field_label_version(
        session, payload.canonical, user.name, f"added {payload.label!r}"
    )
    return wire.FieldLabelOut(
        id=row.id,
        canonical=row.canonical,
        label=row.label,
        scope=row.scope,
        scope_label=scopes.label(row.scope),
        is_active=row.is_active,
        created_by=row.created_by,
    )


@router.post("/field-labels/{label_id}/active", response_model=wire.FieldLabelOut)
def set_field_label_active(
    label_id: int,
    active: bool = Query(...),
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> wire.FieldLabelOut:
    """Switch a label on or off.

    Retiring a wrong label without losing the row, which is what the tool does
    everywhere rather than deleting.

    Args:
        label_id: The row id.
        active: Whether it should resolve.
        session: The request's session.
        user: The caller.

    Returns:
        The updated label.

    Raises:
        HTTPException: 404 when it does not exist.
    """
    require_admin(user)
    row = session.get(models.FieldLabel, label_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"field label {label_id} not found")
    row.is_active = active
    repository.audit(
        session,
        "admin.field_label_active" if active else "admin.field_label_inactive",
        detail=f"{row.canonical}:{row.label}",
        user_id=user.id,
        actor=user.name,
    )
    versions.record_field_label_version(
        session,
        row.canonical,
        user.name,
        f"{'switched on' if active else 'switched off'} {row.label!r}",
    )
    return wire.FieldLabelOut(
        id=row.id,
        canonical=row.canonical,
        label=row.label,
        scope=row.scope,
        scope_label=scopes.label(row.scope),
        is_active=row.is_active,
        created_by=row.created_by,
    )


@router.delete("/field-labels/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_field_label(
    label_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
    _confirmed: None = Depends(require_delete_word),
) -> None:
    """Delete a label.

    Args:
        label_id: The row id.
        session: The request's session.
        user: The caller.

    Raises:
        HTTPException: 404 when it does not exist.
    """
    require_admin(user)
    row = session.get(models.FieldLabel, label_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"field label {label_id} not found")
    canonical, label = row.canonical, row.label
    session.delete(row)
    repository.audit(
        session,
        "admin.field_label_deleted",
        detail=f"{canonical}:{label}",
        user_id=user.id,
        actor=user.name,
    )
    versions.record_field_label_version(session, canonical, user.name, f"deleted {label!r}")


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
    _confirmed: None = Depends(require_delete_word),
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
    _confirmed: None = Depends(require_delete_word),
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
        scope=scopes.for_programme(code).token,
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
    "meaning": "meaning",
    "example": "example",
    "field-label": "field_label",
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


# ------------------------------------------------------------- edit and bulk (ADR-032)


@router.patch("/compliance-rules/{rule_id}", response_model=wire.ComplianceRuleOut)
def edit_compliance_rule(
    rule_id: int,
    payload: wire.ComplianceRuleIn,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
) -> wire.ComplianceRuleOut:
    """Reword a compliance rule. Each edit bumps its version; old findings keep theirs.

    Args:
        rule_id: The rule.
        payload: The new wording, path, scope and reasoning.
        session: The request's session.
        user: The calling administrator.

    Returns:
        The updated rule.

    Raises:
        HTTPException: 404 when it does not exist.
    """
    row = session.get(models.ComplianceRuleRow, rule_id)
    if row is None or row.state == "deleted":
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"compliance rule {rule_id} not found")
    row.name = payload.name.strip()
    row.requirement = {
        "json_path_contains": payload.json_path_contains.strip(),
        "expected_value": payload.expected_value,
    }
    row.scope = payload.scope.strip() or "all"
    row.reasoning = payload.reasoning
    row.version = (row.version or 1) + 1
    session.flush()
    repository.audit(
        session,
        "admin.compliance_rule_edited",
        detail=f"{rule_id}:v{row.version}",
        user_id=user.id,
        actor=user.name,
    )
    return _compliance_out(row)


_BULK_TABLES: Final[dict[str, Any]] = {
    "compliance-rules": models.ComplianceRuleRow,
    "named-values": models.NamedValueRow,
    "aliases": models.AttributeAlias,
    "masked-columns": models.MaskedColumn,
}


@router.post("/{resource}/bulk-delete", response_model=wire.BulkResult)
def bulk_delete(
    resource: str,
    payload: wire.BulkDeleteIn,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
) -> wire.BulkResult:
    """Delete several rows of one resource under one typed word (ADR-032).

    Compliance rules and checks are soft-deleted through the rule lifecycle, so they
    stay restorable; the reference lists are removed outright, as their single
    deletes are.

    Args:
        resource: ``compliance-rules``, ``checks``, ``named-values``, ``aliases`` or
            ``masked-columns``.
        payload: The ids and the typed word.
        session: The request's session.
        user: The calling administrator.

    Returns:
        How many rows went, and which ids were not found.

    Raises:
        HTTPException: 400 without the word, 404 for an unknown resource.
    """
    if payload.confirm.strip().lower() != DELETE_WORD:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"type {DELETE_WORD!r} to confirm; a delete cannot be undone",
        )
    who: dict[str, Any] = {"actor": user.name, "user_id": user.id, "note": "bulk delete"}
    missing: list[int] = []
    deleted = 0
    if resource in ("checks", "compliance-rules"):
        kind = "check" if resource == "checks" else "compliance_rule"
        for rule_id in payload.ids:
            try:
                lifecycle.delete_rule(session, kind, rule_id, **who)
                deleted += 1
            except lifecycle.LifecycleError:
                missing.append(rule_id)
    elif resource in _BULK_TABLES:
        table = _BULK_TABLES[resource]
        for row_id in payload.ids:
            row = session.get(table, row_id)
            if row is None:
                missing.append(row_id)
                continue
            if resource == "masked-columns" and getattr(row, "is_default", False):
                missing.append(row_id)
                continue
            session.delete(row)
            deleted += 1
    else:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no bulk delete for {resource!r}")
    session.flush()
    repository.audit(
        session,
        f"admin.bulk_delete.{resource}",
        detail=f"{deleted} of {len(payload.ids)}",
        user_id=user.id,
        actor=user.name,
    )
    return wire.BulkResult(deleted=deleted, missing=missing)


# --- the administrator's worked examples (Phase 6.13d, ADR-038) -------------------------


#: What each stage is called on the screen, and what an example there teaches.
_STAGE_LABELS: Final[dict[str, tuple[str, str]]] = {
    "s2_extract": (
        "Reading the OSL",
        "A section of the requirements document and the requirements it states.",
    ),
    "s3_describe": (
        "Describing the configuration",
        "A block of the ETL configuration and what it does, in requirement words.",
    ),
    "s4_trace": (
        "Tracing a requirement to the configuration",
        "A requirement and a configuration element, and whether one implements the other.",
    ),
    "admin_judgment": (
        "Judging named values",
        "A judgment check's instruction with values, and the verdict a person would give.",
    ),
    "admin_classify": (
        "Placing a statement",
        "A sentence an administrator wrote, and which rule surface it belongs on.",
    ),
    "training_synthesize": (
        "Drafting a rule from observations",
        "Numbered statements from reviewers, and the rule they amount to.",
    ),
}

#: Pulls the built-in examples out of a template so the console can show them read-only.
_BUILT_IN = re.compile(r"^Example (\d+)\n(.*?)\nAnswer:\n(\{.*?\})\n", re.DOTALL | re.MULTILINE)


def _example_out(row: models.PromptExample) -> wire.ExampleOut:
    return wire.ExampleOut(
        id=row.id,
        stage=row.stage,
        scope=row.scope,
        given={str(k): str(v) for k, v in dict(row.given or {}).items()},
        answer=dict(row.answer or {}),
        note=row.note,
        is_active=row.is_active,
        sort_order=row.sort_order,
        origin=row.origin,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_by=row.updated_by,
        updated_at=row.updated_at,
    )


def _active_count(session: Session, stage: str, exclude: int = 0) -> int:
    """How many of a stage's examples are active, so the cap is enforced where it is set."""
    query = sa.select(sa.func.count(models.PromptExample.id)).where(
        models.PromptExample.stage == stage,
        models.PromptExample.is_active.is_(True),
    )
    if exclude:
        query = query.where(models.PromptExample.id != exclude)
    return int(session.execute(query).scalar_one())


def _guard_cap(session: Session, stage: str, exclude: int = 0) -> None:
    """Refuse an example that would not be shown.

    A prompt carries at most :data:`MAX_PER_STAGE` library examples, so storing a fifth
    active one would leave a row that looks live and reaches no prompt. That is the
    class of silent defect this phase exists to remove.

    Raises:
        HTTPException: 422 when the stage already has its full set active.
    """
    if _active_count(session, stage, exclude) >= example_library.MAX_PER_STAGE:
        raise HTTPException(
            HTTP_422,
            f"{stage} already has {example_library.MAX_PER_STAGE} active examples; "
            "deactivate one first",
        )


def _validated(stage: str, given: Any, answer: Any) -> tuple[dict[str, str], dict[str, Any]]:
    """Validate an example, turning a refusal into a 422 that names what is wrong.

    The personal-data tripwire runs here, on the way in rather than at the prompt: an
    example is text somebody pasted from a real delivery, and the moment they press save
    is the last point at which the person who pasted it can take it out (ADR-003).
    """
    try:
        cleaned, checked = example_library.validate_example(stage, given or {}, answer or {})
    except example_library.ExampleError as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc
    try:
        assert_clean("\n".join(cleaned.values()) + "\n" + json.dumps(checked), stage=stage)
    except PiiDetected as exc:
        raise HTTPException(
            HTTP_422,
            f"this looks like it contains personal data, so it was not saved: {exc}",
        ) from exc
    return cleaned, checked


@router.get("/example-stages", response_model=list[wire.ExampleStageOut])
def list_example_stages(
    _user: CurrentUser = Depends(require_admin),
) -> list[wire.ExampleStageOut]:
    """The stages an administrator may add worked examples to, with the built-in ones.

    Args:
        _user: The calling administrator.

    Returns:
        One entry per stage: what it is called, what an example there teaches, the
        parts an example is made of, and the examples that ship in the prompt.
    """
    out: list[wire.ExampleStageOut] = []
    for stage in example_library.EXAMPLE_STAGES:
        label, description = _STAGE_LABELS.get(stage, (stage, ""))
        template = get_prompt(stage).template
        out.append(
            wire.ExampleStageOut(
                stage=stage,
                label=label,
                description=description,
                fields=[
                    wire.ExampleFieldOut(name=part.name, label=part.label, shape=part.shape)
                    for part in example_library.fields_for(stage)
                ],
                built_in=[
                    wire.BuiltInExample(number=int(number), shown=shown.strip(), answer=answer)
                    for number, shown, answer in _BUILT_IN.findall(template)
                ],
                max_examples=example_library.MAX_PER_STAGE,
            )
        )
    return out


@router.get("/examples", response_model=list[wire.ExampleOut])
def list_examples(
    stage: str = "",
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(require_admin),
) -> list[wire.ExampleOut]:
    """The stored worked examples, newest last within a stage.

    Args:
        stage: One stage, or every stage when omitted.
        session: The request's session.
        _user: The calling administrator.

    Returns:
        The examples, active and inactive alike; the console shows which is which.
    """
    query = sa.select(models.PromptExample).order_by(
        models.PromptExample.stage,
        models.PromptExample.sort_order,
        models.PromptExample.id,
    )
    if stage:
        query = query.where(models.PromptExample.stage == stage)
    return [_example_out(row) for row in session.execute(query).scalars()]


@router.post("/examples", response_model=wire.ExampleOut, status_code=status.HTTP_201_CREATED)
def save_example(
    payload: wire.ExampleIn,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
) -> wire.ExampleOut:
    """Add a worked example to a stage's library (ADR-038).

    The answer is validated against the stage's own schema before anything is written:
    an example the schema would reject teaches the model a shape the pipeline cannot
    parse, which is worse than having no example at all.

    Args:
        payload: The example.
        session: The request's session.
        user: The calling administrator.

    Returns:
        The stored example.

    Raises:
        HTTPException: 422 when the stage is unknown, a part is missing, the answer
            fails the stage's schema, or the stage already has its full set active.
    """
    given, answer = _validated(payload.stage, payload.given, payload.answer)
    if payload.is_active:
        _guard_cap(session, payload.stage)

    row = models.PromptExample(
        stage=payload.stage,
        scope=payload.scope,
        given=given,
        answer=answer,
        note=payload.note,
        origin="admin",
        is_active=payload.is_active,
        sort_order=payload.sort_order,
        created_by=user.name,
        updated_by=user.name,
    )
    session.add(row)
    session.flush()
    versions.record_example_version(session, payload.stage, user.name, f"added {row.id}")
    repository.audit(
        session,
        "admin.example.added",
        detail=f"{payload.stage} {row.id}",
        user_id=user.id,
        actor=user.name,
    )
    return _example_out(row)


@router.patch("/examples/{example_id}", response_model=wire.ExampleOut)
def edit_example(
    example_id: int,
    payload: wire.ExamplePatch,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
) -> wire.ExampleOut:
    """Edit a stored example, or activate and deactivate one.

    Args:
        example_id: The example.
        payload: The fields to change; anything omitted is left alone.
        session: The request's session.
        user: The calling administrator.

    Returns:
        The example as it now stands.

    Raises:
        HTTPException: 404 when there is no such example, 422 when the edit would
            leave an answer the stage's schema rejects or exceed the stage's cap.
    """
    row = session.get(models.PromptExample, example_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no example {example_id}")

    if payload.given is not None or payload.answer is not None:
        given, answer = _validated(
            row.stage,
            payload.given if payload.given is not None else dict(row.given or {}),
            payload.answer if payload.answer is not None else dict(row.answer or {}),
        )
        row.given = given
        row.answer = answer
    if payload.scope is not None:
        row.scope = payload.scope
    if payload.note is not None:
        row.note = payload.note
    if payload.sort_order is not None:
        row.sort_order = payload.sort_order
    if payload.is_active is not None:
        if payload.is_active and not row.is_active:
            _guard_cap(session, row.stage, exclude=row.id)
        row.is_active = payload.is_active
    row.updated_by = user.name

    session.flush()
    versions.record_example_version(session, row.stage, user.name, f"edited {row.id}")
    repository.audit(
        session,
        "admin.example.edited",
        detail=f"{row.stage} {row.id}",
        user_id=user.id,
        actor=user.name,
    )
    return _example_out(row)


#: The keys an extraction answer may carry; a stored rule has more than the prompt does.
_EXTRACTED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "req_type",
        "conditions",
        "values",
        "mode",
        "steps",
        "quantity",
        "action",
        "applies_to",
        "source_text",
        "confidence",
    }
)


def _promote_meaning(session: Session, entry_id: int) -> tuple[str, dict[str, str], dict[str, Any]]:
    """A confirmed requirement mapping, as a tracing example."""
    entry = session.get(models.MeaningEntry, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no meaning entry {entry_id}")
    if entry.status != "confirmed":
        raise HTTPException(HTTP_422, "only a confirmed mapping is worth teaching")
    requirement = (entry.requirement_text or entry.osl_phrase or entry.key).strip()
    element = entry.config_path.strip()
    if not requirement or not element:
        raise HTTPException(HTTP_422, "this mapping names no requirement or no config path")
    if entry.meaning.strip():
        element = f"{element} — {entry.meaning.strip()}"
    return (
        "s4_trace",
        {"requirement": requirement, "element": element},
        {
            "verdict": "implemented",
            "reason": (entry.meaning or "A person confirmed this mapping.").strip(),
            "confidence": 0.95,
        },
    )


def _promote_requirement(
    session: Session, run_id: int, rule_id: str
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """A requirement a reviewer corrected, as an extraction example."""
    row = session.execute(
        sa.select(models.Rule).where(models.Rule.run_id == run_id, models.Rule.rule_id == rule_id)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"rule {rule_id} is not part of run {run_id}"
        )
    body = dict(row.rule or {})
    section = str(body.get("source_text") or "").strip()
    if not section:
        raise HTTPException(HTTP_422, "this requirement quotes no wording to learn from")
    requirement = {
        key: value
        for key, value in body.items()
        if key in _EXTRACTED_KEYS and value not in (None, [], ())
    }
    return "s2_extract", {"section": section}, {"requirements": [requirement]}


def _promote_candidate(
    session: Session, candidate_id: int
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """An approved candidate, as a synthesis example."""
    candidate = session.get(models.RuleCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no candidate {candidate_id}")
    if candidate.status != "approved":
        raise HTTPException(HTTP_422, "only an approved candidate is worth teaching")
    ids = [int(value) for value in (candidate.source_observation_ids or [])]
    rows = (
        session.execute(
            sa.select(models.TrainingObservation)
            .where(models.TrainingObservation.id.in_(ids))
            .order_by(models.TrainingObservation.id)
        )
        .scalars()
        .all()
        if ids
        else []
    )
    statements = "\n".join(
        f"{index}. {row.statement.strip()}" for index, row in enumerate(rows, 1) if row.statement
    )
    if not statements:
        raise HTTPException(HTTP_422, "this candidate has no statement to show")
    body = dict(candidate.body or {})
    body.setdefault("name", candidate.name)
    body.setdefault("target_kind", candidate.target_kind)
    return "training_synthesize", {"statements": statements}, {"rules": [body]}


@router.post(
    "/examples/promote", response_model=wire.ExampleOut, status_code=status.HTTP_201_CREATED
)
def promote_example(
    payload: wire.PromoteIn,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
) -> wire.ExampleOut:
    """Turn a decision a person already confirmed into a worked example (ADR-038).

    The three sources are the three places somebody corrects the model: a confirmed
    requirement mapping, a requirement a reviewer rewrote, and a candidate an
    administrator approved. Nothing is promoted without this call.

    Args:
        payload: Which decision to promote, and where the example applies.
        session: The request's session.
        user: The calling administrator.

    Returns:
        The stored example.

    Raises:
        HTTPException: 404 when the source does not exist, 422 when it was never
            confirmed, carries nothing to teach, or the stage's set is already full.
    """
    if payload.source == "meaning":
        stage, given, answer = _promote_meaning(session, payload.id)
    elif payload.source == "requirement":
        stage, given, answer = _promote_requirement(session, payload.id, payload.rule_id)
    else:
        stage, given, answer = _promote_candidate(session, payload.id)

    given, answer = _validated(stage, given, answer)
    _guard_cap(session, stage)

    row = models.PromptExample(
        stage=stage,
        scope=payload.scope,
        given=given,
        answer=answer,
        note=payload.note,
        origin=f"promoted:{payload.source}:{payload.id}",
        is_active=True,
        created_by=user.name,
        updated_by=user.name,
    )
    session.add(row)
    session.flush()
    versions.record_example_version(session, stage, user.name, f"promoted {row.id}")
    repository.audit(
        session,
        "admin.example.promoted",
        detail=f"{stage} from {payload.source} {payload.id}",
        user_id=user.id,
        actor=user.name,
    )
    return _example_out(row)


def _rule_summary(body: Mapping[str, Any]) -> str:
    """One line describing a stored requirement, for a list an administrator scans."""
    req_type = str(body.get("req_type") or "requirement")
    conditions = body.get("conditions") or []
    if conditions:
        first = conditions[0]
        return (
            f"{req_type} — {first.get('field_name', '')} "
            f"{first.get('operator', '')} {first.get('value', '')}".strip()
        )
    values = body.get("values") or []
    if values:
        return f"{req_type} — {', '.join(str(value) for value in values[:4])}"
    steps = body.get("steps") or []
    if steps:
        return f"{req_type} — {', '.join(str(step) for step in steps[:4])}"
    return req_type


@router.get("/corrections", response_model=list[wire.CorrectionOut])
def list_corrections(
    limit: int = 20,
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(require_admin),
) -> list[wire.CorrectionOut]:
    """Requirements a reviewer rewrote, newest first (Phase 6.13d, ADR-038).

    A correction is the model being told it read a section wrongly, which is what a
    worked example is for. They are listed here so an administrator can teach one;
    nothing is promoted without their click.

    Args:
        limit: How many to return.
        session: The request's session.
        _user: The calling administrator.

    Returns:
        The corrections, each saying which run and requirement it is, the wording it
        quotes, and whether it has been promoted already.
    """
    rows = (
        session.execute(
            sa.select(models.Rule, models.Run.customer_name)
            .join(models.Run, models.Run.id == models.Rule.run_id)
            .where(models.Rule.source == "user")
            .order_by(models.Rule.edited_at.desc().nullslast(), models.Rule.id.desc())
            .limit(max(1, min(limit, 100)))
        )
        .tuples()
        .all()
    )
    promoted = {
        str(origin)
        for origin in session.execute(
            sa.select(models.PromptExample.origin).where(
                models.PromptExample.origin.like("promoted:requirement:%")
            )
        ).scalars()
    }
    out: list[wire.CorrectionOut] = []
    for row, customer in rows:
        body = dict(row.rule or {})
        out.append(
            wire.CorrectionOut(
                run_id=row.run_id,
                rule_id=row.rule_id,
                customer=customer or "",
                source_text=str(body.get("source_text") or ""),
                summary=_rule_summary(body),
                edited_by=row.edited_by,
                edited_at=row.edited_at,
                promoted=f"promoted:requirement:{row.run_id}" in promoted,
            )
        )
    return out
