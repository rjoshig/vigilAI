"""Admin endpoints: templates, named values, checks, compliance, reference data, usage.

Checks are defined as data, not code. The model helps write one *once*
(``POST /admin/checks/draft``); after that the check runs as code on every request at no
token cost (``docs/design.md`` "Configurable checks"). Testing a check never calls the
model.
"""

from __future__ import annotations

import datetime as dt
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

from greenlight_ai import announcements, rehearsal as rehearsal_module, scopes, spend
from greenlight_ai import user_usage, value_report
from greenlight_ai.api import schemas_admin as wire
from greenlight_ai.api.deps import (
    DELETE_WORD,
    assert_capability,
    require_delete_word,
    CurrentUser,
    current_user,
    get_data_dir,
    get_session,
    require_admin,
    require_artifacts,
    require_privacy,
    require_programmes,
    require_reference,
    require_rules,
    require_settings,
    require_teaching,
)
from greenlight_ai.auth.roles import Capability
from greenlight_ai.api.uploads import UploadError, store_upload
from greenlight_ai.checks.expressions import (
    ExpressionError,
    UnresolvedValue,
    evaluate,
    referenced_names,
    validate,
)
from greenlight_ai.checks import guides, layout
from greenlight_ai.resolve import squashed
from greenlight_ai.checks.named_values import NamedValue, resolve, to_number
from greenlight_ai.config import store as config_store
from greenlight_ai.checks import field_labels
from greenlight_ai.db.types import utcnow
from greenlight_ai.db import catalog, models, repository, versions
from greenlight_ai.checks import programme_match
from greenlight_ai.pipeline import guidance
from greenlight_ai.training import demotion, lifecycle
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

# Opening the console at all is the floor for every route here, the read-only ones
# included: a listing tells a caller what the tool checks and who its customers are.
# On top of that floor each route names the capability its own act needs (ADR-049), so
# a reviewer reads the programme list the checks screen depends on but is refused the
# writes that define what a programme is.
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])

#: Which capability a bulk delete needs, by the resource it is deleting. The route
#: serves five tables, so the answer is not known until the parameter is read.
_BULK_CAPABILITY: Final[dict[str, Capability]] = {
    "checks": Capability.MANAGE_RULES,
    "compliance-rules": Capability.MANAGE_RULES,
    "named-values": Capability.MANAGE_RULES,
    "aliases": Capability.MANAGE_REFERENCE,
    "masked-columns": Capability.MANAGE_PRIVACY,
}

#: Which capability a revert needs, by the kind of definition being put back. Reverting
#: is as strong an act as the edit it undoes, so it asks for the same capability.
_VERSION_CAPABILITY: Final[dict[str, Capability]] = {
    "artifact-type": Capability.MANAGE_ARTIFACTS,
    "programme": Capability.MANAGE_PROGRAMMES,
}

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
        layout=[wire.LayoutEntryWire.model_validate(entry) for entry in row.layout_entries or []],
        version=version,
    )


@router.get("/artifact-types", response_model=list[wire.ArtifactTypeOut])
def list_artifact_types(
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    _user: CurrentUser = Depends(require_artifacts),
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
    user: CurrentUser = Depends(require_artifacts),
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
    user: CurrentUser = Depends(require_artifacts),
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
    user: CurrentUser = Depends(require_artifacts),
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


@router.put("/artifact-types/{key}/layout", response_model=wire.ArtifactTypeOut)
def save_layout(
    key: str,
    payload: wire.LayoutIn,
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    user: CurrentUser = Depends(require_artifacts),
) -> wire.ArtifactTypeOut:
    """Replace an artifact type's layout map (Phase 6.21b, ADR-054).

    What this delivery calls each sheet, column and row label the fixed checks look
    for. The ladder reads it as its fourth rung, so an entry never overrules the name
    actually asked for and it costs no model call — recording one turns a delivery the
    model had to reason about into a delivery code resolves. The save is a version.

    Args:
        key: The artifact key.
        payload: The entries.
        session: The request's session.
        data_dir: The shared volume.
        user: The calling administrator.

    Returns:
        The type, with its layout map.

    Raises:
        HTTPException: 404 when the type does not exist, 422 when an entry names a
            kind nothing reads or two entries are the same entry.
    """
    catalog.seed_defaults(session)
    row = session.execute(
        sa.select(models.ArtifactType).where(models.ArtifactType.key == key)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"artifact type {key!r} not found")

    entries: list[layout.LayoutEntry] = []
    for item in payload.entries:
        if item.kind not in layout.KINDS:
            raise HTTPException(HTTP_422, f"{item.kind!r} is not one of {', '.join(layout.KINDS)}")
        entries.append(layout.LayoutEntry.model_validate(item.model_dump()))

    ids = [entry.id for entry in entries]
    if len(set(ids)) != len(ids):
        raise HTTPException(
            HTTP_422,
            "two entries name the same thing in the same scope; put the spellings in one",
        )

    row.layout_entries = [entry.model_dump() for entry in entries]
    session.flush()
    repository.audit(
        session,
        "admin.layout_saved",
        detail=f"{key}:{len(entries)} entries",
        user_id=user.id,
        actor=user.name,
    )
    versions.record_artifact_version(session, row, user.name, "layout edited")
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
    user: CurrentUser = Depends(require_artifacts),
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
    user: CurrentUser = Depends(require_artifacts),
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
    _user: CurrentUser = Depends(require_artifacts),
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
    user: CurrentUser = Depends(require_artifacts),
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
    user: CurrentUser = Depends(require_artifacts),
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
    user: CurrentUser = Depends(require_programmes),
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
    user: CurrentUser = Depends(require_programmes),
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
    user: CurrentUser = Depends(require_rules),
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
    user: CurrentUser = Depends(require_rules),
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
    user: CurrentUser = Depends(require_rules),
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
    user: CurrentUser = Depends(require_rules),
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
    user: CurrentUser = Depends(require_rules),
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
    user: CurrentUser = Depends(require_rules),
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
        alternates=[str(p) for p in (row.requirement or {}).get("alternates", [])],
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
    user: CurrentUser = Depends(require_rules),
) -> wire.ComplianceRuleOut:
    """Create or replace a compliance rule.

    Args:
        payload: The rule.
        session: The request's session.
        user: The caller.

    Returns:
        The stored rule.
    """
    row = session.execute(
        sa.select(models.ComplianceRuleRow).where(models.ComplianceRuleRow.name == payload.name)
    ).scalar_one_or_none()
    if row is None:
        row = models.ComplianceRuleRow(name=payload.name)
        session.add(row)
    row.requirement = {
        "json_path_contains": payload.json_path_contains,
        "alternates": [p.strip() for p in payload.alternates if p.strip()],
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
    user: CurrentUser = Depends(require_rules),
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
    user: CurrentUser = Depends(require_rules),
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
    _user: CurrentUser = Depends(require_settings),
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
    user: CurrentUser = Depends(require_settings),
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
    user: CurrentUser = Depends(require_settings),
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
    user: CurrentUser = Depends(require_settings),
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
    user: CurrentUser = Depends(require_reference),
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
    user: CurrentUser = Depends(require_reference),
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
    user: CurrentUser = Depends(require_reference),
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
    user: CurrentUser = Depends(require_reference),
) -> wire.AliasOut:
    """Add an attribute alias.

    Args:
        payload: The alias.
        session: The request's session.
        user: The caller.

    Returns:
        The stored alias.
    """
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
    user: CurrentUser = Depends(require_reference),
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
    row = session.get(models.AttributeAlias, alias_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"alias {alias_id} not found")
    session.delete(row)
    repository.audit(session, "admin.alias_deleted", detail=row.alias)


@router.get("/masked-columns", response_model=list[wire.MaskedColumnOut])
def list_masked_columns(
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(require_privacy),
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
    user: CurrentUser = Depends(require_privacy),
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
    user: CurrentUser = Depends(require_privacy),
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


@router.get("/value-report", response_model=wire.ValueReportOut)
def value_report_for(
    start: dt.date = Query(...),
    end: dt.date = Query(...),
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> wire.ValueReportOut:
    """What the tool displaced between two dates (Phase 6.16).

    Counted from the run records: distinct orders finalized in the period, multiplied
    by the hours an administrator says a manual check takes. Orders rather than runs,
    because an order checked three times displaced one manual check.

    Args:
        start: First day to count, inclusive.
        end: Last day to count, inclusive.
        session: The request's session.
        _user: The caller.

    Returns:
        The report.

    Raises:
        HTTPException: 422 when the period ends before it starts.
    """
    if end < start:
        raise HTTPException(HTTP_422, "the period ends before it starts")
    hours = int(config_store.resolve(session, "value.hours_per_order").value)
    report = value_report.build(session, start, end, hours)
    return wire.ValueReportOut(
        start=report.start,
        end=report.end,
        days=report.days,
        runs=report.runs,
        orders=report.orders,
        customers=report.customers,
        repeat_runs=report.repeat_runs,
        hours_per_order=report.hours_per_order,
        hours_saved=report.hours_saved,
        working_weeks=report.working_weeks,
    )


@router.get("/usage/by-user", response_model=wire.UsageByUserOut)
def usage_by_user(
    days: int = Query(default=user_usage.DEFAULT_DAYS),
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> wire.UsageByUserOut:
    """Report who is using the tool, and who is having a hard time with it.

    Args:
        days: The period, which must be one the console offers.
        session: The request's session.
        _user: The caller.

    Returns:
        One row per person who submitted something, busiest first, with the
        deployment's own averages beside them.

    Raises:
        HTTPException: 422 when the period is not one of `user_usage.PERIODS`. The
            list is closed rather than a range, so the report cannot be asked for ten
            years of days by editing a URL.
    """
    if days not in user_usage.PERIODS:
        offered = ", ".join(str(period) for period in user_usage.PERIODS)
        raise HTTPException(HTTP_422, f"period must be one of {offered} days")

    period = user_usage.build(session, days)
    rate = spend.rate_for(session)
    return wire.UsageByUserOut(
        start=period.start,
        end=period.end,
        days=period.days,
        runs=period.runs,
        failure_rate=period.failure_rate,
        held_rate=period.held_rate,
        repeat_rate=period.repeat_rate,
        periods=list(user_usage.PERIODS),
        rate_per_million=rate.per_million,
        currency=rate.currency,
        users=[
            wire.UserUsageOut(
                user_id=row.user_id,
                name=row.name,
                username=row.username,
                roles=list(row.roles),
                is_active=row.is_active,
                runs=row.runs,
                finalized=row.finalized,
                needs_review=row.needs_review,
                failed=row.failed,
                held=row.held,
                cancelled=row.cancelled,
                in_flight=row.in_flight,
                orders=row.orders,
                customers=row.customers,
                configurations=row.configurations,
                tokens=row.tokens,
                cost=row.cost,
                cached_calls=row.cached_calls,
                repeat_runs=row.repeat_runs,
                mismatch_runs=row.mismatch_runs,
                high_findings=row.high_findings,
                completed_runs=row.completed_runs,
                failure_rate=row.failure_rate,
                held_rate=row.held_rate,
                repeat_rate=row.repeat_rate,
                high_per_run=row.high_per_run,
                first_run_at=row.first_run_at,
                last_run_at=row.last_run_at,
                per_day=[
                    wire.DayCount(day=entry.day.isoformat(), count=entry.count)
                    for entry in row.per_day
                ],
            )
            for row in period.users
        ],
    )


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
        spend=_spend_out(session, calls),
    )


def _spend_out(session: Session, calls: Sequence[models.LlmCall]) -> wire.SpendOut:
    """What the deployment has spent (Phase 6.21d).

    Two figures side by side, and they answer different questions. The period's spend
    is over whatever window the caller asked for; the month's is over this calendar
    month, because that is the one a budget is set against and the one somebody will be
    asked about.

    Args:
        session: The request's session.
        calls: The period's calls, already loaded by the caller.

    Returns:
        The figures. Every amount is zero when no rate is configured, and the console
        reads ``rate_per_million`` to decide whether to show money at all.
    """
    rate = spend.rate_for(session)
    sent = [call for call in calls if not call.cached]
    tokens = sum(call.prompt_tokens + call.completion_tokens for call in sent)

    today = utcnow().date()
    month = spend.spend_by_day(session, today.replace(day=1), today, rate)
    return wire.SpendOut(
        rate_per_million=rate.per_million,
        currency=rate.currency,
        tokens=tokens,
        cost=round(spend.cost_of(tokens, rate), 2),
        month_tokens=sum(entry.tokens for _day, entry in month),
        month_cost=round(sum(entry.cost for _day, entry in month), 2),
        monthly_warning=rate.monthly_warning,
        cached_calls=len(calls) - len(sent),
        calls=len(sent),
        per_day=[
            wire.DayCost(day=day.isoformat(), tokens=entry.tokens, cost=round(entry.cost, 2))
            for day, entry in month
        ],
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
    _user: CurrentUser = Depends(require_programmes),
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
    user: CurrentUser = Depends(require_programmes),
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
    user: CurrentUser = Depends(require_programmes),
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
        HTTPException: 400 when the word was not typed, 403 when the caller may not
            change this kind of definition, 404 when the version does not exist.
    """
    if payload.confirm.strip().lower() != "revert":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "type 'revert' to confirm; this applies to every future run",
        )
    if kind in _VERSION_CAPABILITY:
        assert_capability(user, _VERSION_CAPABILITY[kind])
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
    user: CurrentUser = Depends(require_rules),
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
        "alternates": [p.strip() for p in payload.alternates if p.strip()],
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
        HTTPException: 400 without the word, 403 when the caller may not change this
            particular resource, 404 for an unknown resource.
    """
    if payload.confirm.strip().lower() != DELETE_WORD:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"type {DELETE_WORD!r} to confirm; a delete cannot be undone",
        )
    if resource in _BULK_CAPABILITY:
        assert_capability(user, _BULK_CAPABILITY[resource])
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
    user: CurrentUser = Depends(require_teaching),
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
    user: CurrentUser = Depends(require_teaching),
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
    user: CurrentUser = Depends(require_teaching),
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


@router.get("/demotion-report", response_model=wire.DemotionReportOut)
def demotion_report(
    customer_name: str = Query(default=""),
    scope: str = Query(default=""),
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> wire.DemotionReportOut:
    """What demotion would do, while it still does nothing (Phase 6.18a, ADR-043).

    The tool has counted every verdict a reviewer gave since Phase 6.13 and acted on
    none of them. This reports what those verdicts add up to: which recurring findings
    have been waved through often enough to have earned their way out of the review
    queue, and which a person has upheld and so never can.

    **Nothing here changes what a reviewer sees.** It is the evidence for the decision
    to let it, which is 6.18b's, and the baseline 6.18c measures against.

    Args:
        customer_name: Limit to one customer, or every customer when empty.
        scope: Limit to one delivery programme, or every programme when empty.
        session: The request's session.
        _user: The caller.

    Returns:
        The report: how many signatures sit in each state, those that would be
        demoted, and those a reviewer has blocked by upholding them.
    """
    query = sa.select(models.FindingSignatureState)
    if customer_name:
        query = query.where(models.FindingSignatureState.customer_name == customer_name)
    if scope:
        query = query.where(models.FindingSignatureState.scope == scope)
    rows = list(
        session.execute(query.order_by(models.FindingSignatureState.last_seen.desc())).scalars()
    )
    return wire.DemotionReportOut(
        counts=demotion.summarize([row.state for row in rows]),
        would_demote=[
            wire.SignatureStateOut.model_validate(row)
            for row in rows
            if row.state == demotion.WOULD_DEMOTE
        ],
        blocked=[
            wire.SignatureStateOut.model_validate(row)
            for row in rows
            if row.state == demotion.BLOCKED
        ],
        shadow=True,
    )


@router.get("/rehearsal", response_model=wire.RehearsalOut)
def rehearsal(
    scope: str = Query(default=""),
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    _user: CurrentUser = Depends(require_artifacts),
) -> wire.RehearsalOut:
    """Try this setup against the stored samples (Phase 6.21f).

    An administrator can define an artifact type, write a guide, confirm meaning
    entries and author checks, and until a real delivery arrives there is no way to
    find out whether any of it fires. The only feedback loop in the product ran through
    somebody else's working day.

    **Nothing is stored and no model is called**, which is what makes this safe to
    press repeatedly while editing. It answers "is this wired up" — not "does it ask
    the right question", which only a person reading the findings can answer.

    Args:
        scope: The programme whose samples to use, or empty for the global ones.
        session: The request's session.
        data_dir: The shared volume the samples live under.
        _user: The caller.

    Returns:
        What the tool read, what resolved, and what would have run.
    """
    result = rehearsal_module.rehearse(session, data_dir, scopes.parse(scope).value)
    return wire.RehearsalOut(
        scope=result.scope,
        artifacts=[
            wire.ArtifactReadingOut(
                key=entry.key,
                label=entry.label,
                sample_count=entry.sample_count,
                sheets=list(entry.sheets),
                resolved=dict(entry.resolved),
                unresolved=list(entry.unresolved),
                error=entry.error,
            )
            for entry in result.artifacts
        ],
        named_values=[
            wire.NamedValueReadingOut(
                name=entry.name,
                description=entry.description,
                found=entry.found,
                value=entry.value,
            )
            for entry in result.named_values
        ],
        checks=[
            wire.CheckReadingOut(
                name=entry.name,
                expression=entry.expression,
                passed=entry.passed,
                detail=entry.detail,
                shadow=entry.shadow,
            )
            for entry in result.checks
        ],
        notes=list(result.notes),
    )


@router.get("/layout-suggestions", response_model=wire.LayoutSuggestionsOut)
def layout_suggestions(
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> wire.LayoutSuggestionsOut:
    """Names the model read because four deterministic rungs could not (Phase 6.21b).

    Each one comes from a run where a check went looking for a sheet, a column or a
    row label, the ladder's four deterministic rungs all missed, and the model — shown
    the names that artifact carries and nothing else — said which one was meant
    (ADR-054). The check then ran, and the run carries a review-severity record saying
    so.

    That is a gap in what the tool has been told about a customer's layout rather than
    a defect in the delivery, and it recurs on every delivery from that customer until
    somebody closes it. Accepting a suggestion is what closes it: from then on the
    ladder's fourth rung resolves the name in code and no call is made.

    **Nothing here is in force.** A suggestion is a suggestion until an administrator
    accepts it (ADR-021).

    Args:
        session: The request's session.
        _user: The caller.

    Returns:
        Every pending suggestion, most-seen first, with the runs it came from.
    """
    # A suggestion is already listed when some entry on that type, at any scope, says
    # this name is spelled that way. Scope is deliberately ignored: an administrator
    # who recorded it for one programme has decided about it, and asking again on the
    # next programme's delivery is how a console trains people to click past it.
    listed: set[tuple[str, str, str, str]] = set()
    for row in session.execute(sa.select(models.ArtifactType)).scalars():
        for raw in row.layout_entries or []:
            if not isinstance(raw, dict):
                continue
            try:
                entry = layout.LayoutEntry.model_validate(raw)
            except ValueError:
                continue
            for name in entry.names:
                listed.add((row.key, entry.kind, squashed(entry.wanted), name))

    seen: dict[tuple[str, str, str, str], list[int]] = {}
    best: dict[tuple[str, str, str, str], wire.LayoutSuggestionOut] = {}
    rows = session.execute(
        sa.select(models.Run.id, models.Run.layout_suggestions).where(
            models.Run.layout_suggestions.is_not(None)
        )
    ).all()
    for run_id, suggestions in rows:
        for raw in suggestions or []:
            try:
                read = layout.LayoutSuggestion.model_validate(raw)
            except ValueError:
                continue
            key = (read.artifact, read.kind, read.wanted, read.found)
            seen.setdefault(key, []).append(int(run_id))
            # Keep the most confident reading's reason: it is the one worth judging.
            if key not in best or read.confidence > best[key].confidence:
                best[key] = wire.LayoutSuggestionOut(
                    artifact=read.artifact,
                    kind=read.kind,
                    wanted=read.wanted,
                    found=read.found,
                    confidence=read.confidence,
                    reason=read.reason,
                )

    out: list[wire.LayoutSuggestionOut] = []
    for key, run_ids in seen.items():
        row_out = best[key]
        row_out.seen = len(run_ids)
        row_out.run_ids = sorted(run_ids)[-10:]
        row_out.already_listed = (key[0], key[1], squashed(key[2]), key[3]) in listed
        out.append(row_out)
    out.sort(key=lambda row: (row.already_listed, -row.seen, row.artifact, row.wanted))
    return wire.LayoutSuggestionsOut(suggestions=out)


@router.post("/layout-suggestions/accept", response_model=wire.ArtifactTypeOut)
def accept_layout_suggestion(
    payload: wire.LayoutAcceptIn,
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    user: CurrentUser = Depends(require_artifacts),
) -> wire.ArtifactTypeOut:
    """Record one read name on its artifact type.

    The act that closes the loop: from here the ladder's fourth rung resolves this
    name in code and the model is not asked again (ADR-054).

    Args:
        payload: Which artifact, kind, wanted name and spelling, and the scope.
        session: The request's session.
        data_dir: The shared volume.
        user: The caller, recorded in the audit log.

    Returns:
        The artifact type, with its new entry.

    Raises:
        HTTPException: 404 when the type does not exist, 422 on an unknown kind.
    """
    if payload.kind not in layout.KINDS:
        raise HTTPException(HTTP_422, f"{payload.kind!r} is not one of {', '.join(layout.KINDS)}")
    row = session.execute(
        sa.select(models.ArtifactType).where(models.ArtifactType.key == payload.artifact)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"artifact type {payload.artifact!r} not found"
        )

    entries = [
        layout.LayoutEntry.model_validate(entry)
        for entry in (row.layout_entries or [])
        if isinstance(entry, dict)
    ]
    wanted_id = layout.entry_id(payload.scope, payload.kind, payload.wanted)
    existing = next((entry for entry in entries if entry.id == wanted_id), None)
    if existing is None:
        entries.append(
            layout.LayoutEntry(
                scope=scopes.token(payload.scope),
                kind=payload.kind,
                wanted=payload.wanted,
                names=(payload.found,),
                note="accepted from what the AI read",
                added_by=user.name,
            )
        )
    elif payload.found not in existing.names:
        entries = [
            (
                entry.model_copy(update={"names": entry.names + (payload.found,)})
                if entry.id == wanted_id
                else entry
            )
            for entry in entries
        ]

    row.layout_entries = [entry.model_dump() for entry in entries]
    session.flush()
    repository.audit(
        session,
        "artifact.layout_accepted",
        None,
        f"{payload.artifact} {payload.kind} {payload.wanted!r} -> {payload.found!r}",
        user_id=user.id,
        actor=user.name,
    )
    versions.record_artifact_version(session, row, user.name, "layout accepted")
    _LOG.info(
        "layout %s %s %r accepted as %r",
        payload.artifact,
        payload.kind,
        payload.wanted,
        payload.found,
    )
    return _artifact_out(
        row, data_dir, version=versions.latest_version(session, "artifact_type", row.key)
    )


@router.get("/keyword-suggestions", response_model=wire.KeywordSuggestionsOut)
def keyword_suggestions(
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> wire.KeywordSuggestionsOut:
    """Words that would have matched a delivery's declared programme (Phase 6.18f).

    Each one comes from a run where the keyword check found none of the declared
    programme's words and the model, asked once, read the delivery as that programme
    anyway. That is a gap in a word list rather than a defect in the delivery, and it
    recurs on every delivery from that customer until somebody closes it.

    **Nothing here is in force.** A suggestion is a suggestion until an administrator
    accepts it (ADR-021).

    Args:
        session: The request's session.
        _user: The caller.

    Returns:
        Every pending suggestion, most-seen first, with the runs it came from.
    """
    listed = {
        scope.code: {programme_match.normalized_key(word) for word in scope.keywords}
        for scope in catalog.load_scopes(session)
    }

    seen: dict[tuple[str, str], list[int]] = {}
    rows = session.execute(
        sa.select(models.Run.id, models.Run.keyword_suggestions).where(
            models.Run.keyword_suggestions.is_not(None)
        )
    ).all()
    for run_id, suggestions in rows:
        for code, phrases in (suggestions or {}).items():
            for phrase in phrases:
                seen.setdefault((str(code), str(phrase)), []).append(int(run_id))

    out = [
        wire.KeywordSuggestionOut(
            scope_code=code,
            phrase=phrase,
            seen=len(run_ids),
            run_ids=sorted(run_ids)[-10:],
            already_listed=programme_match.normalized_key(phrase) in listed.get(code, set()),
        )
        for (code, phrase), run_ids in seen.items()
    ]
    out.sort(key=lambda row: (row.already_listed, -row.seen, row.phrase))
    return wire.KeywordSuggestionsOut(suggestions=out)


@router.post("/keyword-suggestions/accept", response_model=wire.ScopeOut)
def accept_keyword_suggestion(
    payload: wire.AcceptKeywordIn,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_programmes),
) -> wire.ScopeOut:
    """Add one suggested word to a programme's list.

    The act that closes the loop: from here the keyword check matches this customer's
    vocabulary in code, and the model is not asked again (ADR-045).

    Args:
        payload: The programme and the phrase.
        session: The request's session.
        user: The caller, recorded in the audit log.

    Returns:
        The programme, with its new word.

    Raises:
        HTTPException: 404 when the programme does not exist.
    """
    scope = session.execute(
        sa.select(models.RunScope).where(models.RunScope.code == payload.scope_code)
    ).scalar_one_or_none()
    if scope is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no programme {payload.scope_code!r}")

    phrase = " ".join(payload.phrase.split())
    existing = list(scope.keywords)
    key = programme_match.normalized_key(phrase)
    if key not in {programme_match.normalized_key(word) for word in existing}:
        scope.keywords = existing + [phrase]
        repository.audit(
            session,
            "scope.keyword_accepted",
            None,
            f"{scope.code} += {phrase!r}",
            user_id=user.id,
            actor=user.name,
        )
        _LOG.info("keyword %r accepted into programme %s", phrase, scope.code)
    session.flush()
    return wire.ScopeOut(
        id=scope.id,
        code=scope.code,
        label=scope.label,
        description=scope.description,
        standing_instructions=scope.standing_instructions,
        is_active=scope.is_active,
        sort_order=scope.sort_order,
        second_approver=scope.second_approver,
        keywords=list(scope.keywords or []),
        version=versions.latest_version(session, "programme_rules", scope.code),
    )


@router.get("/prompt-budget", response_model=wire.PromptBudgetOut)
def prompt_budget(
    scope_code: str = Query(default=""),
    configuration_id: str = Query(default=""),
    artifact_key: str = Query(default=""),
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> wire.PromptBudgetOut:
    """How much of a prompt's context allowance is already spent (Phase 6.17b).

    A field that states its cap tells an administrator the rule. This is what lets one
    tell them what is *left*, which is the thing they can act on — the eleventh
    configuration note on a configuration is trimmed whether or not anybody knew the
    rule, and its author finds out afterwards, if at all.

    Counted over exactly the lines a prompt carries, by the same function that builds
    them, so the number shown is the number that decides what gets dropped.

    Args:
        scope_code: The delivery programme whose standing instructions to include.
        configuration_id: The configuration whose notes to include.
        artifact_key: The artifact whose guidance to include, when asking about one.
        session: The request's session.
        _user: The caller.

    Returns:
        The caps, what is used, and what is left.
    """
    scope = None
    if scope_code:
        scope = session.execute(
            sa.select(models.RunScope).where(models.RunScope.code == scope_code)
        ).scalar_one_or_none()

    context = guidance.RunGuidance(
        scope_code=scope_code,
        scope_label=scope.label if scope is not None else "",
        scope_instructions=scope.standing_instructions if scope is not None else "",
        config_notes=(
            tuple(repository.active_config_notes(session, configuration_id))
            if configuration_id
            else ()
        ),
        artifact_context={
            artifact.key: artifact.ai_context
            for artifact in catalog.load_artifacts(session)
            if artifact.ai_context.strip()
        },
    )
    found = guidance.budget(context, artifact_key)
    return wire.PromptBudgetOut(
        per_field_cap=found.per_field_cap,
        block_cap=found.block_cap,
        used=found.used,
        remaining=found.remaining,
        lines=found.lines,
        trimmed=found.trimmed,
    )
