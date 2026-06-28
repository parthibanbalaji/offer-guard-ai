# Project context

## What we are building

OfferGuard is an AI-assisted UAE offer-letter review system. Users upload offer
documents, the backend extracts and chunks the content, the system compares
document evidence against a curated UAE employment rule base, and the user gets a
fixed-clause report with citations, scores, risk categories, and human-review
checkpoints.

This is a learning-focused portfolio project and review-support tool. It is not
legal advice.

## Architecture understanding

Most of the system is a deterministic workflow:

```text
upload -> store -> extract -> chunk -> embed -> retrieve evidence -> generate report
```

The truly agentic part is the **Evidence Retrieval Agent**. For each clause, it
must observe the retrieved evidence, decide whether the evidence is sufficient,
act by reranking, expanding the query, retrying, or escalating to HITL, and then
stop when it has enough evidence or cannot proceed safely.

The report generator is a structured generation step. It should not be treated
as the main agent unless it is given goal-directed tools and dynamic decisions.

## Working agreement

- Build flow by flow and file by file.
- Do not bulk-generate large parts of the app.
- Prefer small vertical slices that can be understood, tested, and discussed.
- Keep implementation steps tied to the phase plan in
  `docs/offer-review-agent-plan.md`.
- Explain important design decisions as we go so the project remains useful for
  learning.
- Add tests near the behavior being introduced.
- Keep architecture terms precise: workflow for fixed steps, agent for
  goal-directed dynamic loops.

## Current build direction

Start with foundation and slowly increase capability:

1. Backend foundation, config, health checks, logging, and local services.
2. Upload intake, MinIO storage, PostgreSQL metadata, and queued review jobs.
3. Extraction, guardrails, chunking, and Weaviate hybrid indexing.
4. Curated UAE rule knowledge base.
5. First-pass clause retrieval without agentic retries.
6. Evidence Retrieval Agent loop with observe, decide, act, and HITL.
7. Structured clause findings and final report.
8. HITL UI, evals, and production hardening.
