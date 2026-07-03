"""LangSmith tracing helpers with document-content redaction."""

from collections.abc import Sequence
from dataclasses import asdict, is_dataclass
from typing import Any

from langsmith import traceable

from app.domain.rules import RuleBase
from app.rag.chunking import DocumentChunk
from app.services.documents import DocumentRecord

__all__ = ["traceable"]


def estimate_text_tokens(text: str) -> int:
    """Estimate token count for tracing without requiring provider responses."""
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        return max(1, len(text) // 4) if text else 0


def summarize_texts(texts: Sequence[str]) -> dict[str, int]:
    """Summarize text inputs without returning their content."""
    return {
        "text_count": len(texts),
        "total_chars": sum(len(text) for text in texts),
        "estimated_input_tokens": sum(estimate_text_tokens(text) for text in texts),
    }


def summarize_chunk(chunk: DocumentChunk, *, include_text: bool = False) -> dict[str, Any]:
    """Return trace-safe chunk metadata."""
    summary: dict[str, Any] = {
        "document_id": str(chunk.document_id),
        "chunk_ordinal": chunk.chunk_ordinal,
        "checksum_sha256": chunk.checksum_sha256,
        "language": chunk.language,
        "extraction_quality": chunk.extraction_quality,
        "page_number": chunk.page_number,
        "section_heading": chunk.section_heading,
        "is_suspicious": chunk.is_suspicious,
        "guardrail_flags": list(chunk.guardrail_flags),
        "char_count": len(chunk.text),
        "estimated_tokens": estimate_text_tokens(chunk.text),
    }
    if include_text:
        summary["text"] = chunk.text
    return summary


def summarize_chunks(
    chunks: Sequence[DocumentChunk],
    *,
    include_text: bool = False,
) -> dict[str, Any]:
    """Summarize chunks for trace metadata."""
    return {
        "chunk_count": len(chunks),
        "chunks": [summarize_chunk(chunk, include_text=include_text) for chunk in chunks],
    }


def summarize_vectors(vectors: Sequence[Sequence[float]]) -> dict[str, int | None]:
    """Summarize embedding vectors without logging vector values."""
    return {
        "vector_count": len(vectors),
        "dimensions": len(vectors[0]) if vectors else None,
    }


def serialize_trace_value(value: Any) -> Any:
    """Best-effort JSON-friendly serializer for traced outputs."""
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, tuple):
        return [serialize_trace_value(item) for item in value]
    if isinstance(value, list):
        return [serialize_trace_value(item) for item in value]
    if isinstance(value, dict):
        return {key: serialize_trace_value(item) for key, item in value.items()}
    return value


def process_embedding_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Hide raw embedding text inputs in traces."""
    texts = inputs.get("texts", ())
    return summarize_texts(list(texts))


def process_embedding_outputs(outputs: list[list[float]]) -> dict[str, int | None]:
    """Hide raw embedding vectors in traces."""
    return summarize_vectors(outputs)


def process_index_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Hide raw chunk text while tracing indexing inputs."""
    chunks = list(inputs.get("chunks", ()))
    return summarize_chunks(chunks)


def process_index_outputs(outputs: int) -> dict[str, int]:
    """Trace indexing output count."""
    return {"indexed_count": outputs}


def process_store_chunks_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Hide raw chunk text while tracing Postgres chunk persistence."""
    chunks = list(inputs.get("chunks", ()))
    return {
        "document_id": str(inputs.get("document_id")),
        **summarize_chunks(chunks),
    }


def process_store_chunks_outputs(outputs: int) -> dict[str, int]:
    """Trace stored chunk row count."""
    return {"stored_chunk_count": outputs}


def process_pipeline_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Hide runtime clients and secrets while tracing document preparation."""
    settings = inputs.get("settings")
    return {
        "document_id": str(inputs.get("document_id")),
        "embedding_provider": getattr(settings, "embedding_provider", None),
        "embedding_model": getattr(settings, "embedding_model", None),
        "chunk_target_chars": getattr(settings, "chunk_target_chars", None),
        "chunk_overlap_chars": getattr(settings, "chunk_overlap_chars", None),
    }


def process_pipeline_outputs(outputs: Any) -> dict[str, Any]:
    """Trace document preparation result without full chunk text."""
    return {
        "document_id": str(outputs.document_id),
        "chunk_count": outputs.chunk_count,
        "stored_count": outputs.stored_count,
        "indexed_count": outputs.indexed_count,
        "guardrail_findings": [serialize_trace_value(finding) for finding in outputs.findings],
        "chunk_summary": summarize_chunks(outputs.chunks),
    }


def summarize_document_record(record: DocumentRecord) -> dict[str, Any]:
    """Summarize document metadata for trace hierarchy."""
    return {
        "document_id": str(record.document_id),
        "job_id": str(record.job_id),
        "original_filename": record.original_filename,
        "media_type": record.media_type,
        "size_bytes": record.size_bytes,
        "document_checksum_sha256": record.checksum_sha256,
        "original_storage_key": record.original_storage_key,
        "upload_status": record.upload_status,
        "review_job_status": record.review_job_status,
    }


def summarize_rule_base(rule_base: RuleBase | None) -> dict[str, str | None]:
    """Summarize rule-base identity for trace metadata."""
    if rule_base is None:
        return {
            "rule_base_id": None,
            "rule_base_schema_version": None,
            "rule_base_retrieved_on": None,
        }
    return {
        "rule_base_id": rule_base.rule_base_id,
        "rule_base_schema_version": rule_base.schema_version,
        "rule_base_retrieved_on": rule_base.retrieved_on,
    }


def process_document_run_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Trace document-run inputs without runtime clients or secrets."""
    settings = inputs.get("settings")
    return {
        "document_id": str(inputs.get("document_id")),
        "workflow_stage": "prepare_review",
        "embedding_provider": getattr(settings, "embedding_provider", None),
        "embedding_model": getattr(settings, "embedding_model", None),
        "chunk_target_chars": getattr(settings, "chunk_target_chars", None),
        "chunk_overlap_chars": getattr(settings, "chunk_overlap_chars", None),
    }


def process_document_run_outputs(outputs: Any) -> dict[str, Any]:
    """Trace the top-level document review run result."""
    return {
        "document": summarize_document_record(outputs.document),
        "rule_base": summarize_rule_base(outputs.rule_base),
        "review_job_status": outputs.review_job_status,
        "chunk_count": outputs.indexing_result.chunk_count,
        "stored_count": outputs.indexing_result.stored_count,
        "indexed_count": outputs.indexing_result.indexed_count,
        "guardrail_flags": outputs.guardrail_flags,
        "chunk_summary": summarize_chunks(outputs.indexing_result.chunks),
    }


def process_storage_read_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Trace object-storage read target without client object details."""
    return {"bucket": inputs.get("bucket"), "key": inputs.get("key")}


def process_storage_read_outputs(outputs: bytes) -> dict[str, int]:
    """Trace object-storage read size without content."""
    return {"size_bytes": len(outputs)}


def trace_retrieved_chunks(
    *,
    clause_id: str,
    query: str,
    chunks: Sequence[DocumentChunk],
    include_text: bool = False,
) -> dict[str, Any]:
    """Trace retrieved chunk ids/metadata for future clause retrieval flows."""
    return _trace_retrieved_chunks(
        clause_id=clause_id,
        query=query,
        chunk_summary=summarize_chunks(chunks, include_text=include_text),
    )


@traceable(name="RetrievedChunks", run_type="retriever")
def _trace_retrieved_chunks(
    *,
    clause_id: str,
    query: str,
    chunk_summary: dict[str, Any],
) -> dict[str, Any]:
    """LangSmith-visible retrieval trace payload."""
    return {
        "clause_id": clause_id,
        "query": query,
        "chunk_summary": chunk_summary,
    }
