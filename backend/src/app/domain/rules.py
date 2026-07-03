"""Curated UAE employment rule-base loader."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RuleCitation:
    """Source reference for a rule."""

    source_id: str
    reference: str


@dataclass(frozen=True)
class ClauseRule:
    """One review rule for a fixed clause."""

    rule_id: str
    type: str
    severity: str
    text: str
    recommendation: str
    expected_offer_evidence: tuple[str, ...]
    citations: tuple[RuleCitation, ...]


@dataclass(frozen=True)
class ClauseDefinition:
    """A fixed clause and its associated UAE review rules."""

    clause_id: str
    title: str
    priority: str
    description: str
    search_terms: tuple[str, ...]
    retrieval_queries: tuple[str, ...]
    rules: tuple[ClauseRule, ...]


@dataclass(frozen=True)
class RuleSource:
    """Metadata for an authoritative source used by the rule base."""

    source_id: str
    title: str
    publisher: str
    url: str
    retrieved_on: str
    notes: str


@dataclass(frozen=True)
class RuleBase:
    """Loaded UAE employment rule base."""

    schema_version: str
    rule_base_id: str
    title: str
    jurisdiction: str
    retrieved_on: str
    limitations: tuple[str, ...]
    sources: tuple[RuleSource, ...]
    clauses: tuple[ClauseDefinition, ...]


class RuleBaseError(ValueError):
    """Raised when the curated rule-base file is invalid."""


def default_rule_base_path() -> Path:
    """Return the repository path for the bundled UAE rule base."""
    container_path = Path("/app/knowledge_base/uae_employment_rules.v1.json")
    if container_path.exists():
        return container_path

    source_path = source_rule_base_path()
    if source_path.exists():
        return source_path

    return source_path


def source_rule_base_path() -> Path:
    """Return the rule-base path when running from the source tree."""
    return Path(__file__).resolve().parents[3] / "knowledge_base" / "uae_employment_rules.v1.json"


def load_rule_base(path: str | Path | None = None) -> RuleBase:
    """Load and validate the curated UAE employment rule-base file."""
    rule_base_path = Path(path) if path is not None else default_rule_base_path()
    if not rule_base_path.exists():
        source_path = source_rule_base_path()
        if source_path.exists():
            rule_base_path = source_path

    raw_data = json.loads(rule_base_path.read_text(encoding="utf-8"))
    return parse_rule_base(raw_data)


def parse_rule_base(raw_data: dict[str, Any]) -> RuleBase:
    """Parse rule-base JSON data into immutable clause objects."""
    clauses = tuple(parse_clause(clause) for clause in raw_data["clauses"])
    if not clauses:
        msg = "rule base must define at least one clause"
        raise RuleBaseError(msg)

    clause_ids = [clause.clause_id for clause in clauses]
    if len(clause_ids) != len(set(clause_ids)):
        msg = "rule base clause ids must be unique"
        raise RuleBaseError(msg)

    return RuleBase(
        schema_version=raw_data["schema_version"],
        rule_base_id=raw_data["rule_base_id"],
        title=raw_data["title"],
        jurisdiction=raw_data["jurisdiction"],
        retrieved_on=raw_data["retrieved_on"],
        limitations=tuple(raw_data.get("limitations", ())),
        sources=tuple(parse_source(source) for source in raw_data["sources"]),
        clauses=clauses,
    )


def parse_source(raw_source: dict[str, Any]) -> RuleSource:
    """Parse one source entry."""
    return RuleSource(
        source_id=raw_source["source_id"],
        title=raw_source["title"],
        publisher=raw_source["publisher"],
        url=raw_source["url"],
        retrieved_on=raw_source["retrieved_on"],
        notes=raw_source["notes"],
    )


def parse_clause(raw_clause: dict[str, Any]) -> ClauseDefinition:
    """Parse one clause definition."""
    rules = tuple(parse_rule(rule) for rule in raw_clause["rules"])
    if not rules:
        msg = f"clause {raw_clause['clause_id']} must define at least one rule"
        raise RuleBaseError(msg)

    return ClauseDefinition(
        clause_id=raw_clause["clause_id"],
        title=raw_clause["title"],
        priority=raw_clause["priority"],
        description=raw_clause["description"],
        search_terms=tuple(raw_clause.get("search_terms", ())),
        retrieval_queries=tuple(raw_clause.get("retrieval_queries", ())),
        rules=rules,
    )


def parse_rule(raw_rule: dict[str, Any]) -> ClauseRule:
    """Parse one clause review rule."""
    return ClauseRule(
        rule_id=raw_rule["rule_id"],
        type=raw_rule["type"],
        severity=raw_rule["severity"],
        text=raw_rule["text"],
        recommendation=raw_rule["recommendation"],
        expected_offer_evidence=tuple(raw_rule.get("expected_offer_evidence", ())),
        citations=tuple(parse_citation(citation) for citation in raw_rule["citations"]),
    )


def parse_citation(raw_citation: dict[str, str]) -> RuleCitation:
    """Parse one rule citation."""
    return RuleCitation(
        source_id=raw_citation["source_id"],
        reference=raw_citation["reference"],
    )
