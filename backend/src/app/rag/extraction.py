"""Document text extraction for retrieval indexing."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile


class ExtractionQuality(StrEnum):
    """Coarse quality score for extracted text."""

    GOOD = "good"
    PARTIAL = "partial"
    POOR = "poor"


@dataclass(frozen=True)
class ExtractedSegment:
    """A contiguous extracted text segment, usually one page or one file body."""

    text: str
    page_number: int | None
    section_heading: str | None
    extraction_quality: str


@dataclass(frozen=True)
class ExtractedDocument:
    """Text extracted from an uploaded document."""

    segments: tuple[ExtractedSegment, ...]
    media_type: str
    extension: str
    extraction_quality: str


class UnsupportedExtractionError(ValueError):
    """Raised when no extractor supports the uploaded document."""


def extension_for_filename(filename: str) -> str:
    """Return a normalized file extension."""
    return Path(filename).suffix.lower()


def extract_text_document(content: bytes, media_type: str, extension: str) -> ExtractedDocument:
    """Extract UTF-8 text from a plain text upload."""
    text = content.decode("utf-8", errors="replace")
    quality = quality_for_text(text)
    return ExtractedDocument(
        segments=(
            ExtractedSegment(
                text=text,
                page_number=None,
                section_heading=None,
                extraction_quality=quality,
            ),
        ),
        media_type=media_type,
        extension=extension,
        extraction_quality=quality,
    )


def extract_markdown_document(content: bytes, media_type: str, extension: str) -> ExtractedDocument:
    """Extract readable text from Markdown while preserving headings."""
    text = content.decode("utf-8", errors="replace")
    quality = quality_for_text(text)
    first_heading = first_markdown_heading(text)
    return ExtractedDocument(
        segments=(
            ExtractedSegment(
                text=text,
                page_number=None,
                section_heading=first_heading,
                extraction_quality=quality,
            ),
        ),
        media_type=media_type,
        extension=extension,
        extraction_quality=quality,
    )


def extract_pdf_document(content: bytes, media_type: str, extension: str) -> ExtractedDocument:
    """Extract text from a text-based PDF with LangChain's page loader."""
    try:
        from langchain_community.document_loaders import PyPDFLoader
    except ImportError as exc:  # pragma: no cover - depends on optional install set
        msg = "PDF extraction requires langchain-community and pypdf"
        raise UnsupportedExtractionError(msg) from exc

    temporary_path: str | None = None
    try:
        with NamedTemporaryFile(suffix=extension, delete=False) as temporary_file:
            temporary_file.write(content)
            temporary_path = temporary_file.name

        documents = PyPDFLoader(temporary_path, mode="page").load()
    finally:
        if temporary_path is not None:
            Path(temporary_path).unlink(missing_ok=True)

    segments: list[ExtractedSegment] = []
    for index, document in enumerate(documents, start=1):
        text = document.page_content
        raw_page = document.metadata.get("page")
        page_number = raw_page + 1 if isinstance(raw_page, int) else index
        quality = quality_for_text(text)
        segments.append(
            ExtractedSegment(
                text=text,
                page_number=page_number,
                section_heading=None,
                extraction_quality=quality,
            )
        )

    combined_text = "\n".join(segment.text for segment in segments)
    return ExtractedDocument(
        segments=tuple(segments),
        media_type=media_type,
        extension=extension,
        extraction_quality=quality_for_text(combined_text),
    )


def extract_document(
    content: bytes,
    *,
    filename: str,
    media_type: str,
) -> ExtractedDocument:
    """Dispatch extraction by supported file extension."""
    extension = extension_for_filename(filename)
    if extension == ".txt":
        return extract_text_document(content, media_type, extension)
    if extension in {".md", ".markdown"}:
        return extract_markdown_document(content, media_type, extension)
    if extension == ".pdf":
        return extract_pdf_document(content, media_type, extension)

    msg = f"unsupported extraction extension: {extension or '<none>'}"
    raise UnsupportedExtractionError(msg)


def first_markdown_heading(text: str) -> str | None:
    """Return the first ATX heading from Markdown text."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                return heading
    return None


def quality_for_text(text: str) -> str:
    """Estimate extraction quality from amount of readable text."""
    stripped = text.strip()
    if len(stripped) < 20:
        return ExtractionQuality.POOR.value

    replacement_count = stripped.count("\ufffd")
    readable_count = sum(1 for char in stripped if char.isprintable() or char.isspace())
    readable_ratio = readable_count / len(stripped)
    replacement_ratio = replacement_count / len(stripped)

    if readable_ratio >= 0.95 and replacement_ratio <= 0.01:
        return ExtractionQuality.GOOD.value
    if readable_ratio >= 0.8 and replacement_ratio <= 0.05:
        return ExtractionQuality.PARTIAL.value
    return ExtractionQuality.POOR.value
