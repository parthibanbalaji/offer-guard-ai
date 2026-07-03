from app.domain.rules import load_rule_base


def test_load_rule_base_creates_clause_objects_from_file() -> None:
    rule_base = load_rule_base()

    assert rule_base.rule_base_id == "uae_private_sector_employment_rules_v1"
    assert len(rule_base.clauses) >= 13
    clause_ids = {clause.clause_id for clause in rule_base.clauses}
    assert {
        "probation_period",
        "notice_period",
        "salary_and_compensation",
        "working_hours",
        "annual_leave",
        "sick_leave",
        "termination",
        "end_of_service_gratuity",
        "non_compete_restrictive_covenants",
        "confidentiality",
        "governing_law_jurisdiction",
        "visa_sponsorship_employment_eligibility",
        "missing_unclear_mandatory_terms",
    }.issubset(clause_ids)

    probation = next(
        clause for clause in rule_base.clauses if clause.clause_id == "probation_period"
    )
    assert len(probation.retrieval_queries) >= 3
    assert "probation period" in probation.retrieval_queries[0]
    assert probation.rules
    assert probation.rules[0].text
    assert probation.rules[0].citations

    for clause in rule_base.clauses:
        assert clause.retrieval_queries
        assert all(query.endswith(".") for query in clause.retrieval_queries)
