import pytest

from app.errors import AppError
from app.ingestion.validation import sanitize_filename, validate_upload
from tests.fakes import make_docx, make_pdf

MAX = 1024 * 1024


def test_sanitize_filename_strips_paths_and_control_characters():
    traversal = "..\\evil\\..\\re" + "\x00" + "port.pdf"
    assert sanitize_filename(traversal) == "report.pdf"
    assert sanitize_filename("  notes.md  ") == "notes.md"
    assert len(sanitize_filename("a" * 300 + ".txt")) == 200
    with pytest.raises(AppError):
        sanitize_filename("...")


REJECTED = {
    "unsupported-type": ("notes.exe", b"x", "UNSUPPORTED_FILE_TYPE"),
    "empty": ("empty.txt", b"", "EMPTY_FILE"),
    "too-large": ("big.txt", b"x" * (MAX + 1), "FILE_TOO_LARGE"),
    "fake-pdf": ("fake.pdf", b"not a pdf at all", "FILE_TYPE_MISMATCH"),
    "fake-docx": ("fake.docx", b"not a zip", "FILE_TYPE_MISMATCH"),
    "binary": ("binary.csv", b"a,b\n\x00\xff", "UNSUPPORTED_ENCODING"),
    "latin-1": ("latin.txt", "café".encode("latin-1"), "UNSUPPORTED_ENCODING"),
}


@pytest.mark.parametrize("case", list(REJECTED))
def test_rejected_uploads(case):
    filename, data, code = REJECTED[case]
    with pytest.raises(AppError) as caught:
        validate_upload(filename, data, MAX)
    assert caught.value.code == code


def test_accepted_uploads_report_type_and_hash():
    pdf = validate_upload("a.pdf", make_pdf(["hi"]), MAX)
    assert pdf.document_type == "pdf" and len(pdf.sha256) == 64
    assert validate_upload("b.docx", make_docx([("p", "x")]), MAX).document_type == "docx"
    assert validate_upload("c.markdown", b"# T\n", MAX).document_type == "md"
    assert validate_upload("d.json", b"[]", MAX).document_type == "json"
