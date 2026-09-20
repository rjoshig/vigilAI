"""Versioned definitions with revert (Phase 6.8c, ADR-029).

Every save of an artifact type (its fields, samples, and guide) and every change to
a programme's rule set writes a snapshot of the whole state as the next version.
Ten are listed per object; a version a run inside the retention window still
references is kept beyond the ten. A revert writes an old snapshot back as a new
version, so nothing is ever overwritten and the list itself is the audit trail.

The snapshot carries ids, names, paths and hashes, never a file: sample workbooks
stay on disk while any retained version references them, and a revert re-attaches
them by path.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final, Literal, Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session

from greenlight_ai.db import models
from greenlight_ai.db.types import utcnow

__all__ = [
    "KEEP_VERSIONS",
    "VersionKind",
    "VersionError",
    "artifact_snapshot",
    "current_versions",
    "latest_version",
    "list_versions",
    "programme_snapshot",
    "prune_versions",
    "record_artifact_version",
    "record_programme_version",
    "referenced_sample_paths",
    "remove_orphan_samples",
    "revert",
]

_LOG: Final = logging.getLogger(__name__)

#: How many versions the console lists per object (user decision, Phase 6.8).
KEEP_VERSIONS: Final[int] = 10

VersionKind = Literal["artifact_type", "programme_rules"]

#: Artifact-type fields an administrator edits, in snapshot order.
_ARTIFACT_FIELDS: Final[tuple[str, ...]] = (
    "label",
    "kind",
    "description",
    "ai_context",
    "is_active",
    "is_required",
    "sort_order",
    "notes",
)

#: Sample fields the snapshot keeps; enough to re-create the row on a revert.
_SAMPLE_FIELDS: Final[tuple[str, ...]] = (
    "label",
    "notes",
    "filename",
    "storage_path",
    "sha256",
    "size_bytes",
    "sheets",
    "uploaded_by",
)

#: Programme-rule fields the snapshot keeps.
_RULE_FIELDS: Final[tuple[str, ...]] = ("title", "text", "strictness", "sort_order", "state")


class VersionError(ValueError):
    """A revert that cannot be done: no such version, or nothing to revert onto."""


# --- snapshots -------------------------------------------------------------------------


def artifact_snapshot(row: models.ArtifactType) -> dict[str, Any]:
    """Capture an artifact type with its samples and guide.

    Args:
        row: The stored type, with its samples loaded.

    Returns:
        A JSON-ready dictionary.
    """
    return {
        "key": row.key,
        **{name: getattr(row, name) for name in _ARTIFACT_FIELDS},
        "samples": [
            {"id": sample.id, **{name: getattr(sample, name) for name in _SAMPLE_FIELDS}}
            for sample in row.samples
        ],
        "guide": list(getattr(row, "guide_entries", None) or []),
    }


def programme_snapshot(session: Session, code: str) -> dict[str, Any]:
    """Capture a programme's rule set, deleted rules included.

    Args:
        session: An open session.
        code: The programme.

    Returns:
        A JSON-ready dictionary.
    """
    rows = session.execute(
        sa.select(models.ProgrammeRule)
        .where(models.ProgrammeRule.scope_code == code)
        .order_by(models.ProgrammeRule.sort_order, models.ProgrammeRule.id)
    ).scalars()
    return {
        "code": code,
        "rules": [
            {"id": rule.id, **{name: getattr(rule, name) for name in _RULE_FIELDS}} for rule in rows
        ],
    }


# --- recording -------------------------------------------------------------------------


def _latest(session: Session, kind: str, key: str) -> models.DefinitionVersion | None:
    return session.execute(
        sa.select(models.DefinitionVersion)
        .where(
            models.DefinitionVersion.kind == kind,
            models.DefinitionVersion.object_key == key,
        )
        .order_by(models.DefinitionVersion.version.desc())
        .limit(1)
    ).scalar_one_or_none()


def _record(
    session: Session,
    kind: VersionKind,
    key: str,
    snapshot: dict[str, Any],
    actor: str,
    summary: str,
    reverted_from: int | None = None,
) -> models.DefinitionVersion:
    """Write the next version, unless nothing changed since the last one."""
    latest = _latest(session, kind, key)
    if latest is not None and latest.snapshot == snapshot and reverted_from is None:
        return latest
    row = models.DefinitionVersion(
        kind=kind,
        object_key=key,
        version=(latest.version + 1) if latest is not None else 1,
        snapshot=snapshot,
        summary=(summary or _describe(latest.snapshot if latest else None, snapshot))[:500],
        reverted_from=reverted_from,
        created_by=actor[:200],
    )
    session.add(row)
    session.flush()
    _LOG.info("%s %s: version %d by %s", kind, key, row.version, actor or "?")
    return row


def record_artifact_version(
    session: Session, row: models.ArtifactType, actor: str, summary: str = ""
) -> models.DefinitionVersion:
    """Snapshot an artifact type after a save.

    Args:
        session: An open session.
        row: The type, after the change has been flushed.
        actor: Who saved it.
        summary: What changed, when the caller knows; derived otherwise.

    Returns:
        The version written, or the latest when nothing changed.
    """
    session.flush()
    session.refresh(row)
    return _record(session, "artifact_type", row.key, artifact_snapshot(row), actor, summary)


def record_programme_version(
    session: Session, code: str, actor: str, summary: str = ""
) -> models.DefinitionVersion:
    """Snapshot a programme's rule set after a change.

    Args:
        session: An open session.
        code: The programme.
        actor: Who changed it.
        summary: What changed, when the caller knows; derived otherwise.

    Returns:
        The version written, or the latest when nothing changed.
    """
    session.flush()
    return _record(
        session, "programme_rules", code, programme_snapshot(session, code), actor, summary
    )


def _describe(before: dict[str, Any] | None, after: dict[str, Any]) -> str:
    """One line on what differs between two snapshots."""
    if before is None:
        return "created"
    changed = [
        name
        for name in after
        if name not in ("samples", "guide", "rules") and before.get(name) != after.get(name)
    ]
    parts = [f"{name} changed" for name in changed]
    for collection, noun in (("samples", "sample"), ("guide", "guide entry"), ("rules", "rule")):
        if collection not in after:
            continue
        old = before.get(collection) or []
        new = after.get(collection) or []
        if len(new) > len(old):
            parts.append(f"{noun} added")
        elif len(new) < len(old):
            parts.append(f"{noun} removed")
        elif old != new:
            parts.append(f"{noun} edited")
    return "; ".join(parts) or "saved"


# --- reading ---------------------------------------------------------------------------


def list_versions(
    session: Session, kind: VersionKind, key: str, limit: int = KEEP_VERSIONS
) -> Sequence[models.DefinitionVersion]:
    """The newest versions of one object, newest first.

    Args:
        session: An open session.
        kind: Which definition.
        key: The artifact key or programme code.
        limit: How many to return.

    Returns:
        The versions.
    """
    return list(
        session.execute(
            sa.select(models.DefinitionVersion)
            .where(
                models.DefinitionVersion.kind == kind,
                models.DefinitionVersion.object_key == key,
            )
            .order_by(models.DefinitionVersion.version.desc())
            .limit(limit)
        ).scalars()
    )


def latest_version(session: Session, kind: VersionKind, key: str) -> int:
    """The newest version number of one object, or zero before its first save.

    Args:
        session: An open session.
        kind: Which definition.
        key: The artifact key or programme code.

    Returns:
        The version number.
    """
    latest = _latest(session, kind, key)
    return latest.version if latest is not None else 0


def current_versions(session: Session) -> dict[str, int]:
    """The latest version number of every definition, for a run to record.

    Args:
        session: An open session.

    Returns:
        ``{"artifact_type:<key>": n, "programme_rules:<code>": n}``.
    """
    rows = session.execute(
        sa.select(
            models.DefinitionVersion.kind,
            models.DefinitionVersion.object_key,
            sa.func.max(models.DefinitionVersion.version),
        ).group_by(models.DefinitionVersion.kind, models.DefinitionVersion.object_key)
    ).all()
    return {f"{kind}:{key}": int(version) for kind, key, version in rows}


# --- revert ----------------------------------------------------------------------------


def revert(
    session: Session,
    kind: VersionKind,
    key: str,
    version: int,
    data_dir: Path,
    actor: str,
) -> models.DefinitionVersion:
    """Put an old version back, as a new version.

    Args:
        session: An open session.
        kind: Which definition.
        key: The artifact key or programme code.
        version: The version to restore.
        data_dir: The shared volume, where sample workbooks live.
        actor: Who is reverting.

    Returns:
        The new version that carries the restored state.

    Raises:
        VersionError: When the version does not exist or the object is gone.
    """
    target = session.execute(
        sa.select(models.DefinitionVersion).where(
            models.DefinitionVersion.kind == kind,
            models.DefinitionVersion.object_key == key,
            models.DefinitionVersion.version == version,
        )
    ).scalar_one_or_none()
    if target is None:
        raise VersionError(f"{kind} {key!r} has no version {version}")

    if kind == "artifact_type":
        summary = _restore_artifact(session, key, target.snapshot, data_dir)
        row = session.execute(
            sa.select(models.ArtifactType).where(models.ArtifactType.key == key)
        ).scalar_one()
        session.flush()
        session.refresh(row)
        snapshot = artifact_snapshot(row)
    else:
        summary = _restore_programme(session, key, target.snapshot)
        snapshot = programme_snapshot(session, key)

    return _record(
        session,
        kind,
        key,
        snapshot,
        actor,
        f"reverted to version {version}" + (f"; {summary}" if summary else ""),
        reverted_from=version,
    )


def _restore_artifact(session: Session, key: str, snapshot: dict[str, Any], data_dir: Path) -> str:
    """Write an artifact-type snapshot over the live row; returns caveats."""
    row = session.execute(
        sa.select(models.ArtifactType).where(models.ArtifactType.key == key)
    ).scalar_one_or_none()
    if row is None:
        raise VersionError(f"artifact type {key!r} no longer exists")
    for name in _ARTIFACT_FIELDS:
        if name == "kind" and row.is_builtin:
            continue
        if name in snapshot:
            setattr(row, name, snapshot[name])
    if hasattr(row, "guide_entries"):
        row.guide_entries = list(snapshot.get("guide") or [])

    wanted = {s["storage_path"]: s for s in snapshot.get("samples") or [] if s.get("storage_path")}
    present = {sample.storage_path: sample for sample in row.samples}
    for path, sample in present.items():
        if path not in wanted:
            # The row goes; the file stays while any retained version names it.
            session.delete(sample)
    missing: list[str] = []
    for path, wanted_sample in wanted.items():
        if path in present:
            present[path].label = wanted_sample.get("label", "")
            present[path].notes = wanted_sample.get("notes", "")
            continue
        if not (data_dir / path).exists():
            missing.append(wanted_sample.get("filename") or path)
            continue
        session.add(
            models.ArtifactSample(
                artifact_type_id=row.id,
                **{name: wanted_sample.get(name) for name in _SAMPLE_FIELDS},
            )
        )
    session.flush()
    if missing:
        return "sample file(s) no longer on disk, not restored: " + ", ".join(missing)
    return ""


def _restore_programme(session: Session, code: str, snapshot: dict[str, Any]) -> str:
    """Write a programme-rules snapshot over the live rows; returns caveats."""
    live = {
        rule.id: rule
        for rule in session.execute(
            sa.select(models.ProgrammeRule).where(models.ProgrammeRule.scope_code == code)
        ).scalars()
    }
    seen: set[int] = set()
    for wanted in snapshot.get("rules") or []:
        rule = live.get(int(wanted.get("id", 0)))
        if rule is None:
            # A rule created after this version: re-create it under a new id.
            rule = models.ProgrammeRule(scope_code=code, scope=f"programme:{code}")
            session.add(rule)
        else:
            seen.add(rule.id)
        for name in _RULE_FIELDS:
            if name in wanted:
                setattr(rule, name, wanted[name])
        if rule.state != "deleted":
            rule.deleted_at = None
        elif rule.deleted_at is None:
            rule.deleted_at = utcnow()
    for rule_id, rule in live.items():
        if rule_id not in seen and rule.state != "deleted":
            # Not in the version being restored: it did not exist then, so it goes
            # to deleted, which the Rules screen can still restore for six months.
            rule.state = "deleted"
            rule.deleted_at = utcnow()
    session.flush()
    return ""


# --- retention -------------------------------------------------------------------------


def referenced_sample_paths(session: Session) -> set[str]:
    """Every sample storage path a live sample or a retained version names.

    Args:
        session: An open session.

    Returns:
        The paths a purge must leave on disk.
    """
    paths = set(session.execute(sa.select(models.ArtifactSample.storage_path)).scalars().all())
    for row in session.execute(
        sa.select(models.DefinitionVersion.snapshot).where(
            models.DefinitionVersion.kind == "artifact_type"
        )
    ).scalars():
        for sample in (row or {}).get("samples") or []:
            if sample.get("storage_path"):
                paths.add(sample["storage_path"])
    return paths


def prune_versions(session: Session, keep: int = KEEP_VERSIONS) -> int:
    """Drop versions beyond the newest ``keep`` of each object.

    A version a run that has not expired still names is kept regardless, so a
    finding on that run can always show the definition that produced it.

    Args:
        session: An open session.
        keep: How many to keep per object.

    Returns:
        How many versions were deleted.
    """
    still_needed: set[tuple[str, str, int]] = set()
    for recorded in session.execute(sa.select(models.Run.definition_versions)).scalars():
        for token, version in (recorded or {}).items():
            kind, _, key = str(token).partition(":")
            still_needed.add((kind, key, int(version)))

    deleted = 0
    objects = session.execute(
        sa.select(models.DefinitionVersion.kind, models.DefinitionVersion.object_key).distinct()
    ).all()
    for kind, key in objects:
        older = session.execute(
            sa.select(models.DefinitionVersion)
            .where(
                models.DefinitionVersion.kind == kind,
                models.DefinitionVersion.object_key == key,
            )
            .order_by(models.DefinitionVersion.version.desc())
            .offset(keep)
        ).scalars()
        for row in older:
            if (kind, key, row.version) in still_needed:
                continue
            session.delete(row)
            deleted += 1
    if deleted:
        session.flush()
        _LOG.info("pruned %d definition version(s)", deleted)
    return deleted


def remove_orphan_samples(session: Session, data_dir: Path, template_dir: str) -> int:
    """Delete sample workbooks that no live sample and no retained version names.

    Args:
        session: An open session.
        data_dir: The shared volume.
        template_dir: The sample directory under its ``runs`` folder.

    Returns:
        How many files were removed.
    """
    root = data_dir / "runs" / template_dir
    if not root.exists():
        return 0
    keep = referenced_sample_paths(session)
    removed = 0
    for path in root.rglob("*"):
        if path.is_file() and str(path.relative_to(data_dir)) not in keep:
            path.unlink()
            removed += 1
    if removed:
        _LOG.info("removed %d orphaned sample file(s)", removed)
    return removed
