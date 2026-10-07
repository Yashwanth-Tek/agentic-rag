"""Checks an upload before anything parses it: name, size, type and content signature.

Files are only ever held in memory and parsed as data; nothing is written to disk or executed.
"""

import hashlib
import io
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import PurePath

from app.errors import AppError

SUPPORTED_EXTENSIONS = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".txt": "txt",
    ".md": "md",
    ".markdown": "md",
    ".csv": "csv",
    ".json": "json",
}
MAX_FILENAME_LENGTH = 200
# A DOCX is a zip archive: refuse archives that would inflate far beyond the upload limit.
DOCX_MAX_EXPANSION = 20
DOCX_MAX_ENTRIES = 2000
DOCX_MAX_XML_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class ValidatedUpload:
    filename: str
    document_type: str
    data: bytes
    sha256: str


def file_too_large(max_bytes: int) -> AppError:
    return AppError(
        "FILE_TOO_LARGE", f"The file is larger than the {max_bytes // (1024 * 1024)} MB limit.", 413
    )


def validate_upload(raw_filename: str | None, data: bytes, max_bytes: int) -> ValidatedUpload:
    filename = sanitize_filename(raw_filename or "")
    document_type = SUPPORTED_EXTENSIONS.get(PurePath(filename).suffix.lower())
    if document_type is None:
        allowed = ", ".join(sorted(ext for ext in SUPPORTED_EXTENSIONS if ext != ".markdown"))
        raise AppError("UNSUPPORTED_FILE_TYPE", f"Unsupported file type. Use {allowed}.", 415)
    if not data:
        raise AppError("EMPTY_FILE", "The file is empty.")
    if len(data) > max_bytes:
        raise file_too_large(max_bytes)
    _check_content(document_type, data, max_bytes)
    return ValidatedUpload(filename, document_type, data, hashlib.sha256(data).hexdigest())


def sanitize_filename(raw: str) -> str:
    """Keep a display-safe base name: no path parts, no control characters, bounded length."""
    name = unicodedata.normalize("NFC", raw).replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    name = name.strip().strip(".").strip()
    if len(name) > MAX_FILENAME_LENGTH:
        suffix = PurePath(name).suffix[:20]
        name = name[: MAX_FILENAME_LENGTH - len(suffix)] + suffix
    if not name:
        raise AppError("INVALID_FILENAME", "The file needs a name.")
    return name


def _check_content(document_type: str, data: bytes, max_bytes: int) -> None:
    if document_type == "pdf":
        if b"%PDF-" not in data[:1024]:
            raise _type_mismatch("PDF")
    elif document_type == "docx":
        _check_docx(data, max_bytes)
    else:
        try:
            if b"\x00" in data:
                raise UnicodeDecodeError("utf-8", data, 0, 1, "NUL byte")
            data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise AppError(
                "UNSUPPORTED_ENCODING",
                "This file isn't UTF-8 text. Save it with UTF-8 encoding and upload it again.",
            ) from None


def _check_docx(data: bytes, max_bytes: int) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
    except zipfile.BadZipFile:
        raise _type_mismatch("DOCX") from None
    if not any(entry.filename == "word/document.xml" for entry in entries):
        raise _type_mismatch("DOCX")
    uncompressed = sum(entry.file_size for entry in entries)
    xml = sum(entry.file_size for entry in entries if entry.filename.endswith((".xml", ".rels")))
    if (
        len(entries) > DOCX_MAX_ENTRIES
        or uncompressed > max_bytes * DOCX_MAX_EXPANSION
        or xml > DOCX_MAX_XML_BYTES
    ):
        raise AppError("UNSAFE_FILE", "This DOCX file expands to an unsafe size and was rejected.")


def _type_mismatch(kind: str) -> AppError:
    return AppError(
        "FILE_TYPE_MISMATCH",
        f"The file's contents aren't a valid {kind}. It may be corrupted or renamed.",
        415,
    )
