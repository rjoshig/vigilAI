"""Admin endpoints: templates, named values, checks, compliance, reference data, usage.

Checks are defined as data, not code. The model helps write one *once*
(``POST /admin/checks/draft``); after that the check runs as code on every request at no
token cost (``docs/design.md`` "Configurable checks"). Testing a check never calls the
model.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Any, Final, Sequence

import sqlalchemy as sa
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from vigilai.api import schemas_admin as wire
from vigilai.api.deps import CurrentUser, current_user, get_data_dir, get_session
from vigilai.api.uploads import UploadError, store_upload
from vigilai.checks.expressions import (
    ExpressionError,
    UnresolvedValue,
    evaluate,
    referenced_names,
    validate,
)
from vigilai.checks.named_values import NamedValue, resolve, to_number
from vigilai.db import models, repository
from vigilai.llm.cache import LLMCache
from vigilai.llm.client import LLMError
from vigilai.llm.factory import build_client
from vigilai.llm.prompts import DRAFT_CHECK_PROMPT
from vigilai.llm.prompts.schemas import DraftCheckResponse
from vigilai.parsers.base import ParseError, ReportKind
from vigilai.parsers.masking import DEFAULT_MASKED_COLUMNS
from vigilai.parsers.reports.xlsx import PARSERS, parser_for

__all__ = ["router"]

_LOG: Final = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

#: Where uploaded sample workbooks live on the shared volume.
TEMPLATE_DIR: Final[str] = "templates"

#: Starlette renamed its 422 constant; the number is stable.
HTTP_422: Final[int] = 422


def _admin(user: CurrentUser) -> CurrentUser:
    """Guard admin routes.

    v1 has no login and the admin-ui is separated by URL rather than by role, so this
    always passes. It exists because adding a real check later must be an edit to one
    function, not to twenty routes (ADR-008).

    Args:
        user: The caller.

    Returns:
        The caller.

    Raises:
        HTTPException: 403 when the caller is not an admin.
    """
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin access is required")
    return user


# ---------------------------------------------------------------- report templates


def _template_sheets(path: Path, report_type: str) -> list[str]:
    """List a sample workbook's sheets, for the admin-ui's locator pickers.

    Args:
        path: The stored workbook.
        report_type: Which parser to use.

    Returns:
        The sheet names, or an empty list when the file cannot be read.
    """
    if report_type not in PARSERS or not path.exists():
        return []
    try:
        return [sheet.name for sheet in parser_for(report_type).parse(path).sheets]
    except ParseError:
        return []


@router.get("/templates", response_model=list[wire.TemplateOut])
def list_templates(
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    _user: CurrentUser = Depends(current_user),
) -> list[wire.TemplateOut]:
    """List the uploaded sample workbooks.

    Args:
        session: The request's session.
        data_dir: The shared volume.
        _user: The caller.

    Returns:
        One entry per report type that has a template.
    """
    rows = session.execute(
        sa.select(models.ReportTemplate).order_by(models.ReportTemplate.report_type)
    ).scalars()
    return [
        wire.TemplateOut(
            id=row.id,
            report_type=row.report_type,
            filename=row.filename,
            notes=row.notes,
            created_at=row.created_at,
            sheets=_template_sheets(data_dir / row.storage_path, row.report_type),
        )
        for row in rows
    ]


@router.post("/templates", response_model=wire.TemplateOut, status_code=status.HTTP_201_CREATED)
def upload_template(
    report_type: Annotated[str, File()],
    file: Annotated[UploadFile, File()],
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    user: CurrentUser = Depends(current_user),
) -> wire.TemplateOut:
    """Upload or replace the sample workbook for one report type.

    Args:
        report_type: Which report type this documents.
        file: The workbook.
        session: The request's session.
        data_dir: The shared volume.
        user: The caller.

    Returns:
        The stored template.

    Raises:
        HTTPException: 400 for an unknown report type or a rejected upload.
    """
    _admin(user)
    if report_type not in PARSERS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"unknown report type {report_type!r}; valid types are {', '.join(sorted(PARSERS))}",
        )
    try:
        stored = store_upload(
            file.file,
            file.filename or f"{report_type}.xlsx",
            file.content_type or "",
            report_type,
            data_dir,
            TEMPLATE_DIR,
        )
    except UploadError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    row = session.execute(
        sa.select(models.ReportTemplate).where(models.ReportTemplate.report_type == report_type)
    ).scalar_one_or_none()
    if row is None:
        row = models.ReportTemplate(report_type=report_type)
        session.add(row)
    row.filename = stored.filename
    row.storage_path = stored.storage_key
    session.flush()

    repository.audit(session, "admin.template_uploaded", detail=report_type)
    return wire.TemplateOut(
        id=row.id,
        report_type=row.report_type,
        filename=row.filename,
        notes=row.notes,
        created_at=row.created_at,
        sheets=_template_sheets(data_dir / row.storage_path, report_type),
    )


def _load_templates(session: Session, data_dir: Path) -> dict[ReportKind, Any]:
    """Parse every uploaded sample workbook.

    Args:
        session: An open session.
        data_dir: The shared volume.

    Returns:
        Report kind to parsed document, skipping any that cannot be read. A check tested
        against a missing template reports "could not resolve", which is the same answer
        the run would give.
    """
    documents: dict[ReportKind, Any] = {}
    for row in session.execute(sa.select(models.ReportTemplate)).scalars():
        if row.report_type not in PARSERS:
            continue
        path = data_dir / row.storage_path
        if not path.exists():
            continue
        try:
            documents[row.report_type] = parser_for(row.report_type).parse(path)
        except ParseError as exc:
            _LOG.info("template %s could not be parsed: %s", row.report_type, exc)
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
        report_kind=row.report_type,  # type: ignore[arg-type]
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
    _admin(user)
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
    _admin(user)
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
    _admin(user)

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
    _admin(user)
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
    _admin(user)

    available = (
        payload.report_types
        or sorted(
            row.report_type for row in session.execute(sa.select(models.ReportTemplate)).scalars()
        )
        or sorted(PARSERS)
    )

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
    for value in drafted.named_values:
        if value.report_type not in PARSERS:
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
    _admin(user)
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
    _admin(user)
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
    _admin(user)
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
    from vigilai.checks.definitions import DEFAULT_CATEGORIES

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
    _admin(user)
    existing = list(session.execute(sa.select(models.ReversePassCategoryRow)).scalars())
    if not existing:
        from vigilai.checks.definitions import DEFAULT_CATEGORIES

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
    _admin(user)
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
    _admin(user)
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
    _admin(user)
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
    _admin(user)
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
