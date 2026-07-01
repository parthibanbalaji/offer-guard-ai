# OfferGuard Backend

FastAPI application code lives under `src/app`. Keep the backend organized by runtime concern:

```text
src/app/
  main.py              # FastAPI app factory and lifespan wiring
  api/                 # HTTP API routing
    router.py          # top-level /api router
    v1/
      router.py        # /api/v1 router composition
      routes/          # v1 route handlers
  core/                # cross-cutting runtime setup
    config.py          # environment-backed settings
    resources.py       # application-scoped resource lifecycle
  db/                  # SQLAlchemy ORM models and database mappings
  services/            # reusable integration clients and service helpers
  domain/              # business/domain models and rules
  workflows/           # review workflow orchestration
  agents/              # agent implementations
  rag/                 # retrieval and knowledge-base integration
  guardrails/          # validation and policy checks
  observability/       # logging and telemetry setup
```

## API Versioning

Public API routes are mounted under `/api/{version}`.

Current health endpoints:

```text
GET /api/v1/health
GET /api/v1/ready
POST /api/v1/documents
GET /api/v1/documents
GET /api/v1/documents/{document_id}/download
```

Add new v1 routes under `src/app/api/v1/routes/` and include them from
`src/app/api/v1/router.py`.

When a breaking API change is needed, create a sibling version package instead of changing v1 in
place:

```text
src/app/api/v2/
  router.py
  routes/
```

Then include the v2 router from `src/app/api/router.py`.

## Runtime Resources

`core/resources.py` owns application-scoped lifecycle orchestration. It creates one `AppResources`
bundle during FastAPI startup, stores it on `app.state.resources`, runs dependency readiness
checks, and closes resources on shutdown.

Service-specific client behavior belongs in `services/`:

```text
services/postgres.py   # SQLAlchemy async engine creation/check/close
services/weaviate.py   # Weaviate client creation/check/close
```

Route handlers and workflow code should reuse the app-scoped resources instead of creating new
Postgres engines or Weaviate clients per request.

## Upload Intake

`POST /api/v1/documents` accepts a multipart file upload and validates it while reading the file in
chunks. The upload flow copies the original bytes to MinIO, records document metadata in
PostgreSQL, and creates a queued review job for later processing.

`GET /api/v1/documents` lists stored document metadata from PostgreSQL. `GET
/api/v1/documents/{document_id}/download` streams the original document bytes from MinIO after
looking up the document metadata and storage key in PostgreSQL.

Upload validation is configured with environment variables:

```text
OFFERGUARD_MAX_UPLOAD_BYTES=10485760
OFFERGUARD_ALLOWED_UPLOAD_EXTENSIONS=.txt,.md,.markdown,.pdf
```

## Database Migrations

PostgreSQL schema changes are managed with Alembic. Migration configuration lives in
`alembic.ini`, the Alembic runtime environment lives in `migrations/env.py`, and individual schema
revisions live under `migrations/versions/`.

Run migrations manually from the backend directory with:

```bash
alembic upgrade head
```

In Docker Compose, migrations run as a separate one-shot `migrate` service. The service waits for
PostgreSQL to pass its healthcheck, applies `alembic upgrade head`, and the backend starts only
after that migration step completes successfully.

ORM mappings belong under `src/app/db/`. Keep `domain/` for persistence-independent business rules
and concepts.
