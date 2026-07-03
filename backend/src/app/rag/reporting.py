"""Clause-level report generation for prepared offer documents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from app.core.config import Settings
from app.domain.rules import ClauseDefinition, RuleBase
from app.services.document_chunks import StoredDocumentChunk

REPORT_SYSTEM_PROMPT = """You are OfferGuard's UAE employment offer report analyst.

Your job is to review one fixed UAE employment clause at a time. Use only the supplied offer
chunks and curated rule data. Do not invent facts. If the offer evidence is missing, say it is
missing and score the clause accordingly.

Return strict JSON only, with this shape:
{
  "score": 0-100,
  "summary": "one sentence clause outcome",
  "observations": ["specific observation tied to the offer evidence"],
  "risks": ["risk or gap; empty array if none"],
  "recommendations": ["practical user-facing next step"],
  "evidence_citations": [{"chunk_ordinal": 0, "page_number": 1, "quote": "short exact quote"}],
  "rule_citations": [{"source_id": "string", "reference": "string"}]
}

Scoring guidance:
- 90-100: clause is present, clear, and aligned with the supplied rules.
- 70-89: mostly clear but has minor ambiguity or missing detail.
- 40-69: relevant clause exists but important UAE-rule evidence is absent or unclear.
- 1-39: serious mismatch, high-risk ambiguity, or materially missing protection.
- 0: no relevant offer evidence was found.

Citation rules:
- Evidence citations must refer only to supplied chunk ordinals and include short quotes from them.
- Rule citations must use only the supplied source_id/reference pairs.
- Keep observations concise and suitable for a downloadable report.
- This is AI-assisted review, not legal advice."""


class ReportModel(Protocol):
    """Analyzes one clause against retrieved offer chunks."""

    async def analyze_clause(
        self,
        *,
        clause: ClauseDefinition,
        chunks: tuple[StoredDocumentChunk, ...],
    ) -> dict[str, Any]:
        """Return structured clause analysis."""


class ClauseChunkRetriever(Protocol):
    """Retrieves chunks for one clause before model analysis."""

    async def retrieve_clause_chunks(
        self,
        *,
        clause: ClauseDefinition,
        chunks: tuple[StoredDocumentChunk, ...],
        limit: int,
    ) -> tuple[StoredDocumentChunk, ...]:
        """Return relevant chunks for a clause."""


class ReportGenerationError(RuntimeError):
    """Raised when a report cannot be generated."""


class OpenRouterReportModel:
    """OpenAI-compatible chat model adapter for OpenRouter report generation."""

    def __init__(self, settings: Settings) -> None:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:  # pragma: no cover - depends on runtime install
            msg = "Report generation requires langchain-openai"
            raise RuntimeError(msg) from exc

        api_key = settings.openrouter_api_key
        if api_key is not None and not api_key.get_secret_value():
            api_key = None
        self._model = ChatOpenAI(
            model=settings.report_model,
            api_key=api_key,
            base_url=settings.report_base_url,
            timeout=settings.report_timeout_seconds,
            max_retries=settings.report_max_retries,
            temperature=0,
        )

    async def analyze_clause(
        self,
        *,
        clause: ClauseDefinition,
        chunks: tuple[StoredDocumentChunk, ...],
    ) -> dict[str, Any]:
        """Ask the model for strict JSON clause analysis."""
        prompt = build_clause_prompt(clause, chunks)
        response = await self._model.ainvoke(
            [
                ("system", REPORT_SYSTEM_PROMPT),
                ("user", prompt),
            ]
        )
        content = str(response.content)
        return parse_clause_analysis(content)


@dataclass(frozen=True)
class ReportGenerationResult:
    """Generated report payload and rendered document."""

    report_json: dict[str, Any]
    markdown: str


def select_relevant_chunks(
    clause: ClauseDefinition,
    chunks: tuple[StoredDocumentChunk, ...],
    *,
    limit: int,
) -> tuple[StoredDocumentChunk, ...]:
    """Rank stored chunks by simple lexical overlap with clause retrieval hints."""
    terms = {
        token
        for value in (*clause.search_terms, *clause.retrieval_queries, clause.title)
        for token in tokenize(value)
        if len(token) >= 3
    }
    if not terms:
        return chunks[:limit]

    ranked = sorted(
        chunks,
        key=lambda chunk: (
            -sum(1 for token in tokenize(chunk.text) if token in terms),
            chunk.chunk_ordinal,
        ),
    )
    relevant = [chunk for chunk in ranked if any(token in terms for token in tokenize(chunk.text))]
    return tuple((relevant or ranked)[:limit])


class LexicalClauseChunkRetriever:
    """Fallback clause retriever using stored chunk text."""

    async def retrieve_clause_chunks(
        self,
        *,
        clause: ClauseDefinition,
        chunks: tuple[StoredDocumentChunk, ...],
        limit: int,
    ) -> tuple[StoredDocumentChunk, ...]:
        """Return chunks ranked by lexical overlap."""
        return select_relevant_chunks(clause, chunks, limit=limit)


async def generate_report_payload(
    *,
    document_id: UUID,
    original_filename: str,
    rule_base: RuleBase,
    chunks: tuple[StoredDocumentChunk, ...],
    model: ReportModel,
    relevant_chunk_limit: int,
    chunk_retriever: ClauseChunkRetriever | None = None,
) -> ReportGenerationResult:
    """Generate structured clause analyses and a Markdown report."""
    if not chunks:
        msg = "document must be prepared before report generation"
        raise ReportGenerationError(msg)

    analyses: list[dict[str, Any]] = []
    retriever = chunk_retriever or LexicalClauseChunkRetriever()
    for clause in rule_base.clauses:
        relevant_chunks = await retriever.retrieve_clause_chunks(
            clause=clause,
            chunks=chunks,
            limit=relevant_chunk_limit,
        )
        if not relevant_chunks:
            relevant_chunks = select_relevant_chunks(clause, chunks, limit=relevant_chunk_limit)
        raw_analysis = await model.analyze_clause(clause=clause, chunks=relevant_chunks)
        analyses.append(normalize_clause_analysis(clause, raw_analysis, relevant_chunks))

    report_json: dict[str, Any] = {
        "document_id": str(document_id),
        "original_filename": original_filename,
        "rule_base_id": rule_base.rule_base_id,
        "jurisdiction": rule_base.jurisdiction,
        "clauses": analyses,
        "disclaimer": "AI-assisted review only; this is not legal advice.",
    }
    return ReportGenerationResult(
        report_json=report_json,
        markdown=render_report_markdown(report_json),
    )


def build_clause_retrieval_queries(clause: ClauseDefinition) -> tuple[str, ...]:
    """Build focused semantic retrieval queries for one UAE clause."""
    if clause.retrieval_queries:
        return tuple(
            join_query_parts(clause.title, clause.description, retrieval_query)
            for retrieval_query in clause.retrieval_queries
            if retrieval_query.strip()
        )

    expected_evidence = [
        evidence for rule in clause.rules for evidence in rule.expected_offer_evidence
    ]
    fallback_queries = (*clause.search_terms, *expected_evidence)
    if fallback_queries:
        return tuple(
            join_query_parts(clause.title, clause.description, query)
            for query in fallback_queries
            if query.strip()
        )

    return (join_query_parts(clause.title, clause.description),)


def join_query_parts(*parts: str) -> str:
    """Join non-empty retrieval query parts."""
    return "\n".join(part.strip() for part in parts if part.strip())


def build_clause_retrieval_query(clause: ClauseDefinition) -> str:
    """Build one broad semantic retrieval query for backward compatibility."""
    return join_query_parts(
        clause.title,
        clause.description,
        *clause.search_terms,
        *clause.retrieval_queries,
        *(evidence for rule in clause.rules for evidence in rule.expected_offer_evidence),
        *(rule.text for rule in clause.rules),
    )


def build_clause_prompt(
    clause: ClauseDefinition,
    chunks: tuple[StoredDocumentChunk, ...],
) -> str:
    """Build one user prompt for a clause review."""
    rules = [
        {
            "rule_id": rule.rule_id,
            "severity": rule.severity,
            "text": rule.text,
            "recommendation": rule.recommendation,
            "expected_offer_evidence": list(rule.expected_offer_evidence),
            "citations": [citation.__dict__ for citation in rule.citations],
        }
        for rule in clause.rules
    ]
    evidence = [
        {
            "chunk_ordinal": chunk.chunk_ordinal,
            "page_number": chunk.page_number,
            "section_heading": chunk.section_heading,
            "text": chunk.text,
        }
        for chunk in chunks
    ]
    payload = {
        "clause": {
            "clause_id": clause.clause_id,
            "title": clause.title,
            "description": clause.description,
            "priority": clause.priority,
        },
        "rules": rules,
        "offer_chunks": evidence,
    }
    return json.dumps(payload, ensure_ascii=True, indent=2)


def parse_clause_analysis(content: str) -> dict[str, Any]:
    """Parse model JSON while tolerating fenced output."""
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```").strip()
        stripped = stripped.removesuffix("```").strip()

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        msg = "report model returned invalid JSON"
        raise ReportGenerationError(msg) from exc

    if not isinstance(parsed, dict):
        msg = "report model returned a non-object JSON payload"
        raise ReportGenerationError(msg)
    return parsed


def normalize_clause_analysis(
    clause: ClauseDefinition,
    analysis: dict[str, Any],
    chunks: tuple[StoredDocumentChunk, ...],
) -> dict[str, Any]:
    """Constrain model output to the report schema."""
    valid_ordinals = {chunk.chunk_ordinal for chunk in chunks}
    return {
        "clause_id": clause.clause_id,
        "title": clause.title,
        "priority": clause.priority,
        "score": clamp_score(analysis.get("score")),
        "summary": string_value(analysis.get("summary")),
        "observations": string_list(analysis.get("observations")),
        "risks": string_list(analysis.get("risks")),
        "recommendations": string_list(analysis.get("recommendations")),
        "evidence_citations": [
            citation
            for citation in citation_list(analysis.get("evidence_citations"))
            if citation.get("chunk_ordinal") in valid_ordinals
        ],
        "rule_citations": supplied_rule_citations(clause, analysis.get("rule_citations")),
    }


def supplied_rule_citations(clause: ClauseDefinition, value: object) -> list[dict[str, str]]:
    """Keep only citations that exist in the curated rule data."""
    allowed = {
        (citation.source_id, citation.reference)
        for rule in clause.rules
        for citation in rule.citations
    }
    requested = citation_list(value)
    filtered = [
        {"source_id": str(item["source_id"]), "reference": str(item["reference"])}
        for item in requested
        if (str(item.get("source_id")), str(item.get("reference"))) in allowed
    ]
    if filtered:
        return filtered
    return [
        {"source_id": citation.source_id, "reference": citation.reference}
        for rule in clause.rules
        for citation in rule.citations
    ]


def render_report_markdown(report_json: dict[str, Any]) -> str:
    """Render structured report JSON as a downloadable Markdown document."""
    lines = [
        "# OfferGuard UAE Offer Review Report",
        "",
        f"Document: {report_json['original_filename']}",
        f"Jurisdiction: {report_json['jurisdiction']}",
        "",
        "> AI-assisted review only; this is not legal advice.",
        "",
    ]
    for clause in report_json["clauses"]:
        lines.extend(
            [
                f"## {clause['title']} ({clause['score']}/100)",
                "",
                str(clause["summary"]),
                "",
                "### Observations",
                *bullet_lines(clause["observations"]),
                "",
                "### Risks",
                *bullet_lines(clause["risks"]),
                "",
                "### Recommendations",
                *bullet_lines(clause["recommendations"]),
                "",
                "### Evidence Citations",
                *evidence_lines(clause["evidence_citations"]),
                "",
                "### Rule Citations",
                *rule_lines(clause["rule_citations"]),
                "",
            ]
        )
    return "\n".join(lines)


def bullet_lines(values: list[str]) -> list[str]:
    """Render a Markdown bullet list with a default empty value."""
    return [f"- {value}" for value in values] or ["- None identified."]


def evidence_lines(values: list[dict[str, Any]]) -> list[str]:
    """Render evidence citations."""
    if not values:
        return ["- No direct offer evidence cited."]
    lines: list[str] = []
    for value in values:
        page = value.get("page_number")
        location = f"chunk {value.get('chunk_ordinal')}"
        if page:
            location = f"{location}, page {page}"
        lines.append(f'- {location}: "{string_value(value.get("quote"))}"')
    return lines


def rule_lines(values: list[dict[str, str]]) -> list[str]:
    """Render curated rule citations."""
    return [f"- {value['source_id']}: {value['reference']}" for value in values]


def citation_list(value: object) -> list[dict[str, Any]]:
    """Return a list of dict citations."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def string_list(value: object) -> list[str]:
    """Normalize an unknown value into a list of non-empty strings."""
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def string_value(value: object) -> str:
    """Normalize one string value."""
    text = "" if value is None else str(value).strip()
    return text or "No clear evidence found."


def clamp_score(value: object) -> int:
    """Return an integer score in the report range."""
    if not isinstance(value, int | float | str | bytes | bytearray):
        return 0
    try:
        score = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, score))


def tokenize(value: str) -> tuple[str, ...]:
    """Tokenize text for lightweight chunk relevance ranking."""
    cleaned = "".join(character.lower() if character.isalnum() else " " for character in value)
    return tuple(cleaned.split())
