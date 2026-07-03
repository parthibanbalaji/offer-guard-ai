"""Sentence-aware document chunking."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from app.guardrails.input import flags_for_text
from app.rag.extraction import ExtractedDocument, ExtractedSegment

MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
MARKDOWN_HEADER_KEYS = (
    "Header 6",
    "Header 5",
    "Header 4",
    "Header 3",
    "Header 2",
    "Header 1",
)


@dataclass(frozen=True)
class ChunkingConfig:
    """Controls chunk size and continuity."""

    target_chars: int = 1200
    overlap_chars: int = 180


@dataclass(frozen=True)
class DocumentChunk:
    """A traceable chunk ready for persistence and indexing."""

    document_id: UUID
    chunk_ordinal: int
    text: str
    checksum_sha256: str
    language: str
    extraction_quality: str
    page_number: int | None
    section_heading: str | None
    is_suspicious: bool
    guardrail_flags: tuple[str, ...]


def chunk_document(
    extracted_document: ExtractedDocument,
    *,
    document_id: UUID,
    config: ChunkingConfig | None = None,
) -> tuple[DocumentChunk, ...]:
    """Split extracted text into LangChain chunks with OfferGuard metadata."""
    chunking_config = config or ChunkingConfig()
    chunks: list[DocumentChunk] = []

    for segment in extracted_document.segments:
        for text, heading, force_isolated in iter_segment_blocks(segment):
            flags = flags_for_text(text)
            overlap_chars = 0 if flags or force_isolated else chunking_config.overlap_chars
            for chunk_text, chunk_heading in split_text_with_langchain(
                text,
                section_heading=heading,
                is_markdown=extracted_document.extension in {".md", ".markdown"},
                target_chars=chunking_config.target_chars,
                overlap_chars=overlap_chars,
            ):
                chunks.append(
                    build_chunk(
                        document_id=document_id,
                        chunk_ordinal=len(chunks),
                        text=chunk_text,
                        segment=segment,
                        section_heading=chunk_heading,
                        guardrail_flags=flags_for_text(chunk_text),
                    )
                )

    return tuple(chunks)


def build_chunk(
    *,
    document_id: UUID,
    chunk_ordinal: int,
    text: str,
    segment: ExtractedSegment,
    section_heading: str | None,
    guardrail_flags: tuple[str, ...],
) -> DocumentChunk:
    """Build chunk metadata for a text span."""
    normalized_text = normalize_whitespace(text)
    return DocumentChunk(
        document_id=document_id,
        chunk_ordinal=chunk_ordinal,
        text=normalized_text,
        checksum_sha256=sha256(normalized_text.encode("utf-8")).hexdigest(),
        language=detect_language(normalized_text),
        extraction_quality=segment.extraction_quality,
        page_number=segment.page_number,
        section_heading=section_heading or segment.section_heading,
        is_suspicious=bool(guardrail_flags),
        guardrail_flags=guardrail_flags,
    )


def iter_segment_blocks(segment: ExtractedSegment) -> Iterable[tuple[str, str | None, bool]]:
    """Yield text blocks, isolating suspicious lines and tracking Markdown headings."""
    current_heading = segment.section_heading
    normal_lines: list[str] = []

    def flush_normal() -> Iterable[tuple[str, str | None, bool]]:
        nonlocal normal_lines
        text = "\n".join(normal_lines).strip()
        normal_lines = []
        if text:
            yield text, current_heading, False

    for line in segment.text.splitlines():
        heading_match = MARKDOWN_HEADING_RE.match(line)
        if heading_match:
            yield from flush_normal()
            current_heading = heading_match.group(1).strip()
            continue

        if flags_for_text(line):
            yield from flush_normal()
            suspicious_text = normalize_whitespace(line)
            if suspicious_text:
                yield suspicious_text, current_heading, True
            continue

        normal_lines.append(line)

    yield from flush_normal()


def split_text_with_langchain(
    text: str,
    *,
    section_heading: str | None,
    is_markdown: bool,
    target_chars: int,
    overlap_chars: int,
) -> tuple[tuple[str, str | None], ...]:
    """Split text with LangChain splitters and return text plus heading metadata."""
    if is_markdown:
        return split_markdown_with_langchain(
            text,
            section_heading=section_heading,
            target_chars=target_chars,
            overlap_chars=overlap_chars,
        )

    splitter = make_recursive_splitter(target_chars=target_chars, overlap_chars=overlap_chars)
    return tuple(
        (normalize_whitespace(chunk), section_heading)
        for chunk in splitter.split_text(text)
        if normalize_whitespace(chunk)
    )


def split_markdown_with_langchain(
    text: str,
    *,
    section_heading: str | None,
    target_chars: int,
    overlap_chars: int,
) -> tuple[tuple[str, str | None], ...]:
    """Split Markdown with LangChain heading metadata, then budget each section."""
    from langchain_text_splitters import MarkdownHeaderTextSplitter

    markdown_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[
            ("#", "Header 1"),
            ("##", "Header 2"),
            ("###", "Header 3"),
            ("####", "Header 4"),
            ("#####", "Header 5"),
            ("######", "Header 6"),
        ],
        strip_headers=False,
    )
    recursive_splitter = make_recursive_splitter(
        target_chars=target_chars,
        overlap_chars=overlap_chars,
    )
    split_documents = markdown_splitter.split_text(text)
    chunks: list[tuple[str, str | None]] = []
    for document in recursive_splitter.split_documents(split_documents):
        chunk_text = normalize_whitespace(document.page_content)
        if not chunk_text:
            continue
        chunks.append((chunk_text, heading_from_metadata(document.metadata) or section_heading))

    return tuple(chunks)


def make_recursive_splitter(*, target_chars: int, overlap_chars: int):
    """Create the LangChain splitter used for sentence-aware budgeting."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    return RecursiveCharacterTextSplitter(
        chunk_size=target_chars,
        chunk_overlap=overlap_chars,
        length_function=len,
        separators=[
            "\n\n",
            "\n",
            ". ",
            "! ",
            "? ",
            "; ",
            ", ",
            " ",
            "",
        ],
    )


def heading_from_metadata(metadata: dict[str, object]) -> str | None:
    """Return the deepest Markdown header preserved by LangChain."""
    for key in MARKDOWN_HEADER_KEYS:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def normalize_whitespace(text: str) -> str:
    """Collapse repeated whitespace for stable checksums and embeddings."""
    return re.sub(r"\s+", " ", text).strip()


def detect_language(text: str) -> str:
    """Return a conservative language code for extracted offer text."""
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return "und"
    ascii_letters = [char for char in letters if char.isascii()]
    if len(ascii_letters) / len(letters) >= 0.9:
        return "en"
    return "und"
