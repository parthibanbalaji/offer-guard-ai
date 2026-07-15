"""Build and run RAGAS evals for the bundled offer-review datasets.

The eval unit is one offer document checked against one rule-base clause. That gives coverage for
both the retrieval step (did we retrieve the right offer evidence for the clause?) and generation
step (did the generated clause analysis stay grounded and answer the criterion?).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from app.core.config import Settings
from app.domain.rules import ClauseDefinition, RuleBase, load_rule_base
from app.rag.chunking import ChunkingConfig, chunk_document
from app.rag.embeddings import create_embedding_model
from app.rag.extraction import extract_document
from app.rag.reporting import (
    LexicalClauseChunkRetriever,
    OpenRouterReportModel,
    build_clause_retrieval_queries,
    build_clause_retrieval_query,
    normalize_clause_analysis,
)
from app.services.document_chunks import StoredDocumentChunk
from app.services.weaviate import (
    EVAL_CHUNK_COLLECTION,
    close_weaviate_client,
    create_weaviate_client,
    index_document_chunks,
    list_indexed_document_chunks,
)
from app.workflows.report_generation import WeaviateClauseChunkRetriever

DEFAULT_DATASET_DIR = Path(__file__).parent / "datasets" / "sample_offers_v1"
DEFAULT_EXPECTED_OUTCOMES = DEFAULT_DATASET_DIR / "expected_outcomes.json"
DEFAULT_GROUND_TRUTH = DEFAULT_DATASET_DIR / "ground_truth.json"
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "experiments" / "ragas_offer_review_v1"
DEFAULT_RETRIEVAL_LIMIT = 5


@dataclass(frozen=True)
class OfferCase:
    """One synthetic offer fixture and its expected outcome labels."""

    filename: str
    path: Path
    case_summary: str
    expected_outcomes: dict[str, str]
    ground_truth: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class GeneratedClauseAnswer:
    """Generated clause response plus structured metadata."""

    text: str
    raw_analysis: dict[str, Any]


def load_offer_cases(
    dataset_dir: Path,
    expected_outcomes_path: Path,
    ground_truth_path: Path | None = DEFAULT_GROUND_TRUTH,
) -> tuple[OfferCase, ...]:
    """Load PDF fixtures and the case-level expected-outcome manifest."""
    manifest = json.loads(expected_outcomes_path.read_text(encoding="utf-8"))
    ground_truth_manifest = load_ground_truth_manifest(ground_truth_path)
    cases = manifest["cases"]
    pdf_paths = sorted(dataset_dir.glob("*.pdf"))
    if not pdf_paths:
        msg = f"no PDF fixtures found in {dataset_dir}"
        raise ValueError(msg)

    default_outcome = str(manifest.get("default_expected_outcome", "not_primary_fixture_focus"))
    offer_cases: list[OfferCase] = []
    for path in pdf_paths:
        raw_case = cases.get(path.name, {})
        raw_ground_truth = ground_truth_manifest.get(path.name, {})
        offer_cases.append(
            OfferCase(
                filename=path.name,
                path=path,
                case_summary=str(raw_case.get("case_summary", "")),
                expected_outcomes={
                    str(clause_id): str(outcome)
                    for clause_id, outcome in raw_case.get("expected_outcomes", {}).items()
                }
                | {"*": default_outcome},
                ground_truth={
                    str(clause_id): truth
                    for clause_id, truth in raw_ground_truth.items()
                    if isinstance(truth, dict)
                },
            )
        )
    return tuple(offer_cases)


def load_ground_truth_manifest(path: Path | None) -> dict[str, dict[str, dict[str, Any]]]:
    """Load optional fixture-specific ground truth."""
    if path is None or not path.exists():
        return {}
    raw_data = json.loads(path.read_text(encoding="utf-8"))
    cases = raw_data.get("cases", {})
    if not isinstance(cases, dict):
        return {}
    return {
        str(filename): {
            str(clause_id): truth
            for clause_id, truth in raw_case.items()
            if isinstance(truth, dict)
        }
        for filename, raw_case in cases.items()
        if isinstance(raw_case, dict)
    }


def settings_for_eval() -> Settings:
    """Load settings from the nearest project env file for CLI eval runs."""
    root_env = Path(__file__).resolve().parents[2] / ".env"
    defaults = {"database_url": "postgresql+asyncpg://eval:eval@localhost:5432/offerguard_eval"}
    if root_env.exists():
        return Settings(_env_file=root_env, **defaults)
    return Settings(_env_file=None, **defaults)


def filter_offer_cases(
    offer_cases: tuple[OfferCase, ...],
    selected_files: tuple[str, ...],
) -> tuple[OfferCase, ...]:
    """Filter offer cases by filename or 1-based fixture prefix."""
    if not selected_files:
        return offer_cases

    selected = {value.strip() for value in selected_files if value.strip()}
    filtered = tuple(
        offer_case
        for offer_case in offer_cases
        if offer_case.filename in selected
        or Path(offer_case.filename).stem in selected
        or offer_case.filename[:2] in selected
    )
    missing = selected - {
        value
        for offer_case in filtered
        for value in (offer_case.filename, Path(offer_case.filename).stem, offer_case.filename[:2])
    }
    if missing:
        msg = f"selected fixture files were not found: {', '.join(sorted(missing))}"
        raise ValueError(msg)
    return filtered


def extract_offer_chunks(
    path: Path, *, chunk_target_chars: int, chunk_overlap_chars: int
) -> tuple[StoredDocumentChunk, ...]:
    """Extract and chunk a fixture PDF into stored-chunk shaped values."""
    document_id = uuid5(NAMESPACE_URL, path.as_uri())
    extracted = extract_document(
        path.read_bytes(),
        filename=path.name,
        media_type="application/pdf",
    )
    chunks = chunk_document(
        extracted,
        document_id=document_id,
        config=ChunkingConfig(
            target_chars=chunk_target_chars,
            overlap_chars=chunk_overlap_chars,
        ),
    )
    created_at = datetime(2026, 7, 14, tzinfo=UTC)
    return tuple(
        StoredDocumentChunk(
            id=uuid5(NAMESPACE_URL, f"{path.as_uri()}#chunk-{chunk.chunk_ordinal}"),
            document_id=document_id,
            chunk_ordinal=chunk.chunk_ordinal,
            text=chunk.text,
            checksum_sha256=chunk.checksum_sha256,
            language=chunk.language,
            extraction_quality=chunk.extraction_quality,
            page_number=chunk.page_number,
            section_heading=chunk.section_heading,
            is_suspicious=chunk.is_suspicious,
            guardrail_flags=chunk.guardrail_flags,
            created_at=created_at,
        )
        for chunk in chunks
    )


async def build_ragas_rows(
    *,
    rule_base: RuleBase,
    offer_cases: tuple[OfferCase, ...],
    retrieval_limit: int,
    answer_mode: str,
    settings: Settings | None,
    chunk_target_chars: int,
    chunk_overlap_chars: int,
    retriever_mode: str,
    weaviate_client: Any | None = None,
    eval_collection: str = EVAL_CHUNK_COLLECTION,
) -> list[dict[str, Any]]:
    """Create one RAGAS row for every offer and every review criterion."""
    rows: list[dict[str, Any]] = []
    model = OpenRouterReportModel(settings) if answer_mode == "generate" and settings else None

    for offer_case in offer_cases:
        chunks = await prepare_offer_chunks(
            offer_case,
            settings=settings,
            weaviate_client=weaviate_client,
            retriever_mode=retriever_mode,
            eval_collection=eval_collection,
            chunk_target_chars=chunk_target_chars,
            chunk_overlap_chars=chunk_overlap_chars,
        )
        retriever = build_clause_retriever(
            settings=settings,
            weaviate_client=weaviate_client,
            retriever_mode=retriever_mode,
            eval_collection=eval_collection,
            document_id=(
                chunks[0].document_id if chunks else uuid5(NAMESPACE_URL, offer_case.path.as_uri())
            ),
        )
        for clause in rule_base.clauses:
            relevant_chunks = await retriever.retrieve_clause_chunks(
                clause=clause,
                chunks=chunks,
                limit=retrieval_limit,
            )
            expected_outcome = expected_outcome_for(offer_case, clause)
            reference = reference_answer_for(offer_case, clause, expected_outcome)
            generated_answer = await generate_clause_answer(
                answer_mode=answer_mode,
                model=model,
                clause=clause,
                chunks=relevant_chunks,
                reference=reference,
            )
            rows.append(
                build_ragas_row(
                    offer_case=offer_case,
                    clause=clause,
                    chunks=relevant_chunks,
                    answer=generated_answer,
                    expected_outcome=expected_outcome,
                    reference=reference,
                )
            )

    return rows


async def prepare_offer_chunks(
    offer_case: OfferCase,
    *,
    settings: Settings | None,
    weaviate_client: Any | None,
    retriever_mode: str,
    eval_collection: str,
    chunk_target_chars: int,
    chunk_overlap_chars: int,
) -> tuple[StoredDocumentChunk, ...]:
    """Return chunks from the eval vector collection, indexing once when needed."""
    if retriever_mode != "weaviate":
        return extract_offer_chunks(
            offer_case.path,
            chunk_target_chars=chunk_target_chars,
            chunk_overlap_chars=chunk_overlap_chars,
        )

    if settings is None or weaviate_client is None:
        msg = "--retriever-mode weaviate requires real settings and a Weaviate client"
        raise ValueError(msg)

    document_id = uuid5(NAMESPACE_URL, offer_case.path.as_uri())
    indexed = await list_indexed_document_chunks(
        weaviate_client,
        document_id=document_id,
        collection_name=eval_collection,
    )
    if indexed:
        return tuple(indexed_properties_to_stored_chunk(properties) for properties in indexed)

    extracted = extract_document(
        offer_case.path.read_bytes(),
        filename=offer_case.path.name,
        media_type="application/pdf",
    )
    document_chunks = chunk_document(
        extracted,
        document_id=document_id,
        config=ChunkingConfig(
            target_chars=chunk_target_chars,
            overlap_chars=chunk_overlap_chars,
        ),
    )
    await index_document_chunks(
        weaviate_client,
        document_chunks,
        create_embedding_model(settings),
        collection_name=eval_collection,
    )
    return tuple(
        document_chunk_to_stored_chunk(offer_case.path, chunk) for chunk in document_chunks
    )


def build_clause_retriever(
    *,
    settings: Settings | None,
    weaviate_client: Any | None,
    retriever_mode: str,
    eval_collection: str,
    document_id: Any,
) -> Any:
    """Build the clause retriever for the selected eval mode."""
    if retriever_mode == "weaviate":
        if settings is None:
            msg = "--retriever-mode weaviate requires real settings"
            raise ValueError(msg)
        return WeaviateClauseChunkRetriever(
            document_id=document_id,
            weaviate_client=weaviate_client,
            settings=settings,
            collection_name=eval_collection,
        )
    return LexicalClauseChunkRetriever()


def document_chunk_to_stored_chunk(path: Path, chunk: Any) -> StoredDocumentChunk:
    """Convert a freshly chunked document value into a stored-chunk shaped value."""
    return StoredDocumentChunk(
        id=uuid5(NAMESPACE_URL, f"{path.as_uri()}#chunk-{chunk.chunk_ordinal}"),
        document_id=chunk.document_id,
        chunk_ordinal=chunk.chunk_ordinal,
        text=chunk.text,
        checksum_sha256=chunk.checksum_sha256,
        language=chunk.language,
        extraction_quality=chunk.extraction_quality,
        page_number=chunk.page_number,
        section_heading=chunk.section_heading,
        is_suspicious=chunk.is_suspicious,
        guardrail_flags=chunk.guardrail_flags,
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
    )


def indexed_properties_to_stored_chunk(properties: dict[str, Any]) -> StoredDocumentChunk:
    """Convert Weaviate chunk properties into a stored-chunk shaped value."""
    document_id = uuid_from_property(properties["document_id"])
    chunk_ordinal = int(properties["chunk_ordinal"])
    return StoredDocumentChunk(
        id=uuid5(NAMESPACE_URL, f"weaviate:{document_id}:{chunk_ordinal}"),
        document_id=document_id,
        chunk_ordinal=chunk_ordinal,
        text=str(properties["text"]),
        checksum_sha256=str(properties["checksum_sha256"]),
        language=str(properties["language"]),
        extraction_quality=str(properties["extraction_quality"]),
        page_number=optional_int(properties.get("page_number")),
        section_heading=optional_str(properties.get("section_heading")),
        is_suspicious=bool(properties.get("is_suspicious", False)),
        guardrail_flags=tuple(str(flag) for flag in properties.get("guardrail_flags", [])),
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
    )


def uuid_from_property(value: object) -> UUID:
    """Parse a UUID property from Weaviate."""
    return UUID(str(value))


def optional_int(value: object) -> int | None:
    """Return an optional int."""
    return int(value) if isinstance(value, int | float | str) and str(value) else None


def optional_str(value: object) -> str | None:
    """Return an optional string."""
    text = "" if value is None else str(value).strip()
    return text or None


async def generate_clause_answer(
    *,
    answer_mode: str,
    model: OpenRouterReportModel | None,
    clause: ClauseDefinition,
    chunks: tuple[StoredDocumentChunk, ...],
    reference: str,
) -> GeneratedClauseAnswer:
    """Generate or synthesize the answer field consumed by generation metrics."""
    if answer_mode == "generate":
        if model is None:
            msg = "--answer-mode generate requires model settings"
            raise ValueError(msg)
        raw_analysis = await model.analyze_clause(clause=clause, chunks=chunks)
        normalized = normalize_clause_analysis(clause, raw_analysis, chunks)
        return GeneratedClauseAnswer(
            text=analysis_to_text(normalized),
            raw_analysis=normalized,
        )

    return GeneratedClauseAnswer(
        text=reference,
        raw_analysis={
            "summary": reference,
            "observations": [],
            "risks": [],
            "recommendations": [],
            "score": None,
        },
    )


def build_ragas_row(
    *,
    offer_case: OfferCase,
    clause: ClauseDefinition,
    chunks: tuple[StoredDocumentChunk, ...],
    answer: GeneratedClauseAnswer,
    expected_outcome: str,
    reference: str,
) -> dict[str, Any]:
    """Build a RAGAS-compatible row with OfferGuard metadata preserved."""
    expected_evidence = expected_evidence_for(offer_case, clause)
    return {
        "sample_id": f"{Path(offer_case.filename).stem}:{clause.clause_id}",
        "offer_filename": offer_case.filename,
        "case_summary": offer_case.case_summary,
        "criteria_id": clause.clause_id,
        "criteria_title": clause.title,
        "expected_outcome": expected_outcome,
        "rule_ids": [rule.rule_id for rule in clause.rules],
        "question": build_question(offer_case, clause),
        "answer": answer.text,
        "reference": reference,
        "ground_truth": reference,
        "contexts": [chunk.text for chunk in chunks],
        "retrieved_context_ids": [str(chunk.chunk_ordinal) for chunk in chunks],
        "retrieval_query": build_clause_retrieval_query(clause),
        "retrieval_queries": list(build_clause_retrieval_queries(clause)),
        "expected_evidence": expected_evidence,
        "rule_citations": [
            {"source_id": citation.source_id, "reference": citation.reference}
            for rule in clause.rules
            for citation in rule.citations
        ],
        "raw_analysis": answer.raw_analysis,
    }


def build_question(offer_case: OfferCase, clause: ClauseDefinition) -> str:
    """Build the criterion-specific user input for RAGAS."""
    expected_evidence = sorted(
        {evidence for rule in clause.rules for evidence in rule.expected_offer_evidence}
    )
    return (
        f"Review {offer_case.filename} for the UAE employment criterion "
        f"'{clause.title}'. Determine whether the offer evidence is acceptable, risky, "
        f"missing, or unclear. Check: {', '.join(expected_evidence)}."
    )


def build_reference_answer(clause: ClauseDefinition, expected_outcome: str) -> str:
    """Build the expected answer for a single clause criterion."""
    rules = " ".join(f"{rule.rule_id}: {rule.text}" for rule in clause.rules)
    recommendations = " ".join(rule.recommendation for rule in clause.rules)
    expected_evidence = ", ".join(
        sorted({evidence for rule in clause.rules for evidence in rule.expected_offer_evidence})
    )
    return (
        f"Expected outcome: {expected_outcome}. The review must evaluate {clause.title} "
        f"using evidence for {expected_evidence}. Applicable rules: {rules} "
        f"Recommended handling: {recommendations}"
    )


def reference_answer_for(
    offer_case: OfferCase,
    clause: ClauseDefinition,
    expected_outcome: str,
) -> str:
    """Return fixture-specific ground truth when available."""
    ground_truth = offer_case.ground_truth.get(clause.clause_id, {})
    reference = ground_truth.get("reference")
    if isinstance(reference, str) and reference.strip():
        return reference.strip()
    return build_reference_answer(clause, expected_outcome)


def expected_evidence_for(offer_case: OfferCase, clause: ClauseDefinition) -> list[str]:
    """Return fixture-specific required evidence when available."""
    ground_truth = offer_case.ground_truth.get(clause.clause_id, {})
    required_evidence = ground_truth.get("required_offer_evidence")
    if isinstance(required_evidence, list):
        return sorted(str(item).strip() for item in required_evidence if str(item).strip())
    return sorted({evidence for rule in clause.rules for evidence in rule.expected_offer_evidence})


def analysis_to_text(analysis: dict[str, Any]) -> str:
    """Flatten structured report JSON into one response string for RAGAS."""
    sections = [
        f"Score: {analysis.get('score')}",
        f"Summary: {analysis.get('summary')}",
        "Observations: " + "; ".join(str(item) for item in analysis.get("observations", [])),
        "Risks: " + "; ".join(str(item) for item in analysis.get("risks", [])),
        "Recommendations: " + "; ".join(str(item) for item in analysis.get("recommendations", [])),
    ]
    return "\n".join(section for section in sections if section.strip())


def expected_outcome_for(offer_case: OfferCase, clause: ClauseDefinition) -> str:
    """Return the expected outcome label for a clause in a fixture."""
    return offer_case.expected_outcomes.get(
        clause.clause_id,
        offer_case.expected_outcomes.get("*", "not_primary_fixture_focus"),
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write JSONL rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")


def write_json(path: Path, payload: Any) -> None:
    """Write a formatted JSON document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), "utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSONL rows."""
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def ragas_dataset_from_rows(rows: list[dict[str, Any]]) -> Any:
    """Return only the columns used directly by the built-in RAGAS metrics."""
    try:
        from datasets import Dataset
    except ImportError as exc:
        msg = "Hugging Face datasets is unavailable. Install with: pip install -e .[eval]"
        raise RuntimeError(msg) from exc

    return Dataset.from_list(
        [
            {
                "question": row["question"],
                "answer": row["answer"],
                "contexts": row["contexts"],
                "ground_truth": row["ground_truth"],
                "reference": row["reference"],
            }
            for row in rows
        ]
    )


def load_ragas_metrics() -> list[Any]:
    """Load a broad metric set compatible with RAGAS 0.2+."""
    try:
        from ragas.metrics import (
            answer_correctness,
            answer_relevancy,
            context_precision,
            context_recall,
            faithfulness,
        )
    except ImportError as exc:
        msg = "RAGAS metrics are unavailable. Install the backend eval extra first."
        raise RuntimeError(msg) from exc

    return [
        context_precision,
        context_recall,
        faithfulness,
        answer_relevancy,
        answer_correctness,
    ]


def run_ragas(
    rows: list[dict[str, Any]],
    *,
    settings: Settings,
    judge_model: str | None,
) -> dict[str, Any]:
    """Run RAGAS over prepared rows."""
    try:
        from ragas import evaluate
    except ImportError as exc:
        msg = "RAGAS is unavailable. Install with: pip install -e .[eval]"
        raise RuntimeError(msg) from exc

    result = evaluate(
        ragas_dataset_from_rows(rows),
        metrics=load_ragas_metrics(),
        llm=build_ragas_judge_llm(settings, judge_model=judge_model),
        embeddings=build_ragas_judge_embeddings(settings),
        raise_exceptions=False,
    )
    if hasattr(result, "to_pandas"):
        metric_rows = json.loads(result.to_pandas().to_json(orient="records"))
        return {
            "summary": ragas_result_summary(result),
            "rows": merge_score_rows(rows, metric_rows),
        }
    return {"summary": ragas_result_summary(result)}


def merge_score_rows(
    rows: list[dict[str, Any]],
    metric_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach eval metadata to RAGAS metric rows."""
    metadata_keys = (
        "sample_id",
        "offer_filename",
        "criteria_id",
        "criteria_title",
        "expected_outcome",
        "rule_ids",
        "retrieved_context_ids",
    )
    return [
        {key: row[key] for key in metadata_keys} | metric_row
        for row, metric_row in zip(rows, metric_rows, strict=True)
    ]


def build_ragas_judge_llm(settings: Settings, *, judge_model: str | None) -> Any:
    """Build the real judge LLM used by RAGAS metrics."""
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        msg = "RAGAS judge LLM requires langchain-openai"
        raise RuntimeError(msg) from exc

    api_key = settings.openrouter_api_key
    return ChatOpenAI(
        model=judge_model or settings.report_model,
        api_key=api_key,
        base_url=settings.report_base_url,
        timeout=settings.report_timeout_seconds,
        max_retries=settings.report_max_retries,
        temperature=0,
    )


def build_ragas_judge_embeddings(settings: Settings) -> Any:
    """Build the real embeddings model used by RAGAS semantic metrics."""
    try:
        from langchain_openai import OpenAIEmbeddings
    except ImportError as exc:
        msg = "RAGAS judge embeddings require langchain-openai"
        raise RuntimeError(msg) from exc

    configured_api_key = (
        settings.openrouter_api_key.get_secret_value()
        if settings.openrouter_api_key is not None
        else None
    )
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        api_key=configured_api_key or None,
        base_url=settings.embedding_base_url,
        timeout=settings.embedding_timeout_seconds,
        max_retries=settings.embedding_max_retries,
        retry_min_seconds=settings.embedding_retry_min_seconds,
        retry_max_seconds=settings.embedding_retry_max_seconds,
    )


def ragas_result_summary(result: Any) -> dict[str, Any]:
    """Convert a RAGAS result object into JSON-safe summary data."""
    try:
        return dict(result)
    except (KeyError, TypeError, ValueError):
        pass

    items = getattr(result, "items", None)
    if callable(items):
        return dict(items())

    repr_dict = getattr(result, "_repr_dict", None)
    if isinstance(repr_dict, dict):
        return repr_dict

    return {"result": str(result)}


async def async_main(args: argparse.Namespace) -> None:
    """Build the eval dataset and optionally run RAGAS scoring."""
    needs_real_settings = (
        args.answer_mode == "generate"
        or args.retriever_mode == "weaviate"
        or args.run_ragas
        or args.input_jsonl is not None
    )
    settings = settings_for_eval() if needs_real_settings else None
    if args.input_jsonl is not None:
        rows = read_jsonl(args.input_jsonl)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        if args.run_ragas:
            if settings is None:
                msg = "--run-ragas requires real settings"
                raise ValueError(msg)
            scores = run_ragas(rows, settings=settings, judge_model=args.judge_model)
            write_json(args.output_dir / "ragas_scores.json", scores)
        return

    rule_base = load_rule_base(args.rule_base)
    offer_cases = filter_offer_cases(
        load_offer_cases(args.dataset_dir, args.expected_outcomes, args.ground_truth),
        tuple(args.files),
    )
    weaviate_client = (
        create_weaviate_client(settings) if args.retriever_mode == "weaviate" else None
    )
    try:
        rows = await build_ragas_rows(
            rule_base=rule_base,
            offer_cases=offer_cases,
            retrieval_limit=args.retrieval_limit,
            answer_mode=args.answer_mode,
            settings=settings,
            chunk_target_chars=args.chunk_target_chars,
            chunk_overlap_chars=args.chunk_overlap_chars,
            retriever_mode=args.retriever_mode,
            weaviate_client=weaviate_client,
            eval_collection=args.eval_collection,
        )

        dataset_path = args.output_dir / "ragas_dataset.jsonl"
        metadata_path = args.output_dir / "metadata.json"
        write_jsonl(dataset_path, rows)
        write_json(
            metadata_path,
            {
                "dataset_rows": len(rows),
                "offer_count": len(offer_cases),
                "criteria_count": len(rule_base.clauses),
                "rule_base_id": rule_base.rule_base_id,
                "answer_mode": args.answer_mode,
                "retriever_mode": args.retriever_mode,
                "eval_collection": args.eval_collection
                if args.retriever_mode == "weaviate"
                else None,
                "selected_files": args.files,
                "retrieval_limit": args.retrieval_limit,
                "generated_at": datetime.now(UTC).isoformat(),
            },
        )

        if args.run_ragas:
            if settings is None:
                msg = "--run-ragas requires real settings"
                raise ValueError(msg)
            scores = run_ragas(rows, settings=settings, judge_model=args.judge_model)
            write_json(args.output_dir / "ragas_scores.json", scores)
    finally:
        await close_weaviate_client(weaviate_client)


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--expected-outcomes", type=Path, default=DEFAULT_EXPECTED_OUTCOMES)
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GROUND_TRUTH)
    parser.add_argument("--rule-base", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--input-jsonl",
        type=Path,
        default=None,
        help="Score an existing RAGAS JSONL dataset instead of rebuilding rows.",
    )
    parser.add_argument("--retrieval-limit", type=int, default=DEFAULT_RETRIEVAL_LIMIT)
    parser.add_argument("--chunk-target-chars", type=int, default=1200)
    parser.add_argument("--chunk-overlap-chars", type=int, default=180)
    parser.add_argument(
        "--files",
        action="append",
        default=[],
        help=(
            "Run a selected fixture by full filename, stem, or 1-based prefix like 01. "
            "Can be passed multiple times."
        ),
    )
    parser.add_argument(
        "--retriever-mode",
        choices=("lexical", "weaviate"),
        default="lexical",
        help="lexical is offline; weaviate indexes/reuses the real eval vector collection.",
    )
    parser.add_argument(
        "--eval-collection",
        default=EVAL_CHUNK_COLLECTION,
        help="Weaviate collection used for real eval indexing.",
    )
    parser.add_argument(
        "--judge-model",
        default=None,
        help="Judge model for RAGAS. Defaults to the configured report model.",
    )
    parser.add_argument(
        "--answer-mode",
        choices=("reference", "generate"),
        default="reference",
        help=(
            "reference writes a deterministic smoke-test answer; generate calls the configured "
            "report model and is the mode to use for production generation evals."
        ),
    )
    parser.add_argument(
        "--run-ragas",
        action="store_true",
        help="Run RAGAS scoring after writing the JSONL dataset.",
    )
    return parser


def main() -> None:
    """CLI entrypoint."""
    asyncio.run(async_main(build_parser().parse_args()))


if __name__ == "__main__":
    main()
