"""Upload validation and storage on the shared volume.

Uploads are the one place untrusted bytes enter the system, so the checks are explicit:
extension, declared content type, and size, all before anything is written. Files land
under a per-run directory keyed by the run id, which keeps the purge job a directory
delete rather than a search.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Final

__all__ = ["UploadError", "StoredFile", "ALLOWED", "MAX_UPLOAD_BYTES", "store_upload", "safe_name"]

_LOG: Final = logging.getLogger(__name__)

#: Extension to the content types a browser may legitimately send for it. Checking both
#: rather than either: an extension alone is trivially wrong, and browsers disagree
#: about spreadsheet types often enough that the type alone rejects valid files.
ALLOWED: Final[dict[str, frozenset[str]]] = {
    ".docx": frozenset(
        {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/octet-stream",
            "",
        }
    ),
    ".json": frozenset(
        {"application/json", "text/json", "text/plain", "application/octet-stream", ""}
    ),
    ".xlsx": frozenset(
        {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
            "application/octet-stream",
            "",
        }
    ),
}

#: 50 MiB, matching `GREENLIGHT_AI_MAX_UPLOAD_MB` in `.env.example`.
MAX_UPLOAD_BYTES: Final[int] = 50 * 1024 * 1024

#: Read in 1 MiB blocks so a large workbook is never held in memory twice.
_BLOCK: Final[int] = 1024 * 1024

_UNSAFE: Final = re.compile(r"[^A-Za-z0-9._-]+")


class UploadError(Exception):
    """An upload was rejected. The message is safe to show the user."""


@dataclass(frozen=True, slots=True)
class StoredFile:
    """A file written to the shared volume.

    Attributes:
        kind: Which input this is, e.g. ``"osl"`` or ``"dirt"``.
        filename: The original name, sanitised.
        storage_key: Path relative to the data directory.
        sha256: The content hash, used for the run fingerprint.
        size_bytes: How large it is.
    """

    kind: str
    filename: str
    storage_key: str
    sha256: str
    size_bytes: int


def safe_name(filename: str) -> str:
    """Reduce an uploaded name to something safe to put on disk.

    Args:
        filename: The name the browser sent.

    Returns:
        The basename with unusual characters replaced. Directory components are dropped
        entirely, so a name like ``../../etc/passwd`` cannot escape the run directory.
    """
    base = Path(filename).name or "upload"
    cleaned = _UNSAFE.sub("_", base).strip("._") or "upload"
    return cleaned[:200]


def store_upload(
    stream: BinaryIO,
    filename: str,
    content_type: str,
    kind: str,
    data_dir: Path,
    run_key: str,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> StoredFile:
    """Validate an upload and write it to the shared volume.

    Args:
        stream: The uploaded bytes.
        filename: The name the browser sent.
        content_type: The declared type.
        kind: Which input this is.
        data_dir: The shared volume.
        run_key: The per-run directory name.
        max_bytes: The size limit.

    Returns:
        A record of what was written.

    Raises:
        UploadError: When the extension, the content type, or the size is not allowed.
            The partial file is removed, so a rejected upload leaves nothing behind.
    """
    name = safe_name(filename)
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED:
        allowed = ", ".join(sorted(ALLOWED))
        seen = suffix or "a file with no extension"
        raise UploadError(f"{name}: only {allowed} files are accepted, not {seen}")
    declared = (content_type or "").split(";")[0].strip().lower()
    if declared not in ALLOWED[suffix]:
        raise UploadError(f"{name}: content type {declared!r} does not match a {suffix} file")

    target_dir = data_dir / "runs" / run_key
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{kind}{suffix}"

    digest = hashlib.sha256()
    written = 0
    try:
        with target.open("wb") as handle:
            while True:
                block = stream.read(_BLOCK)
                if not block:
                    break
                written += len(block)
                if written > max_bytes:
                    raise UploadError(
                        f"{name}: larger than the {max_bytes // (1024 * 1024)} MB limit"
                    )
                digest.update(block)
                handle.write(block)
    except UploadError:
        target.unlink(missing_ok=True)
        raise

    if written == 0:
        target.unlink(missing_ok=True)
        raise UploadError(f"{name}: the file is empty")

    _LOG.info("stored upload kind=%s bytes=%d", kind, written)
    return StoredFile(
        kind=kind,
        filename=name,
        storage_key=str(target.relative_to(data_dir)),
        sha256=digest.hexdigest(),
        size_bytes=written,
    )
