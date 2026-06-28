# OfferGuard AI

OfferGuard AI is a local, production-style system for reviewing UAE job-offer documents with
grounded retrieval, explicit guardrails, human approval, evaluation, and observability. It is an
educational portfolio project, not legal advice.

## Services

| Service | Local port | Responsibility |
|---|---:|---|
| Frontend | 3000 | Upload and review UI |
| Backend | 8000 | FastAPI, LangGraph workflow, guardrails, and APIs |
| PostgreSQL | internal | Document metadata, workflow state, reviews, and feedback |
| Weaviate | 8081 / 50051 | Hybrid offer-document and knowledge-base retrieval indexes |
| MinIO | 9000 / 9001 | S3-compatible document objects and local administration UI |

Uploaded files are objects in MinIO. PostgreSQL stores their metadata and object keys; Weaviate
stores rebuildable vector projections, hybrid-search indexes, and citation metadata. These stores
have separate lifecycles and backup needs.

## Run locally

Docker Desktop must be running:

```bash
docker compose up --build
```

Then open:

- UI: <http://localhost:3000>
- API docs: <http://localhost:8000/docs>
- Weaviate API: <http://localhost:8081>
- MinIO console: <http://localhost:9001>

Copy `.env.example` to `.env` before changing the local credentials. Never reuse the example
credentials outside local development.

## Repository structure

```text
backend/
  src/app/           # FastAPI application package
  tests/             # Unit and integration tests
  evals/             # Evaluation datasets and experiments
  knowledge_base/    # Curated, attributed UAE guidance
  scripts/           # Operator and developer commands
frontend/
  src/               # React upload and human-review interface
compose.yaml          # Complete local service topology
docs/                 # Architecture and engineering decisions
```

The upload endpoint used by the UI (`POST /api/v1/documents`) is the next vertical slice. The UI
is present now so that API work is designed against a real user flow rather than an abstract route.

Read `PROJECT_CONTEXT.md` before implementation work. This project should be built flow by flow and
file by file; the Evidence Retrieval Agent is the agentic core, while fixed ingestion and report
assembly steps should remain ordinary workflow code.

For the vector database decision, see `docs/vector-database-choice.md`.
