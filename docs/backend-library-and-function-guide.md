# Backend Library and Function Guide

This guide lists the main Python libraries, built-in modules, and project functions used in the
backend so far, with the reason each one exists in the application.

## Runtime Frameworks

| Library / module | Used in | Purpose |
|---|---|---|
| `fastapi` | `app.main`, `app.api.*` | Defines the HTTP API application, routes, dependency injection, request objects, file uploads, and HTTP errors. |
| `fastapi.FastAPI` | `app.main.create_app` | Creates the ASGI web application. |
| `fastapi.APIRouter` | `app.api.router`, `app.api.v1.router`, route modules | Groups routes by API version and feature. |
| `fastapi.UploadFile` | `app.api.v1.routes.documents`, `app.services.uploads` | Represents uploaded files without forcing the whole file into memory. |
| `fastapi.File` | `app.api.v1.routes.documents` | Marks an endpoint parameter as multipart file input. |
| `fastapi.Depends` | `app.api.v1.routes.documents` | Injects settings into route handlers. |
| `fastapi.Request` | route handlers | Gives access to app-scoped resources such as Postgres engine and storage client. |
| `fastapi.HTTPException` | route handlers and upload service | Returns controlled HTTP errors such as 404, 413, and 415. |
| `fastapi.responses.StreamingResponse` | document download route | Streams downloaded MinIO bytes back to the browser. |
| `uvicorn` | Docker command / local run | ASGI server that runs the FastAPI app. |

## Data Validation and Settings

| Library / module | Used in | Purpose |
|---|---|---|
| `pydantic.BaseModel` | API response schemas | Defines typed JSON response models for health, upload, and document list responses. |
| `pydantic.Field` | `app.core.config.Settings` | Adds validation rules, such as upload size being greater than zero. |
| `pydantic.SecretStr` | `app.core.config.Settings` | Stores sensitive config values like database and S3 credentials without accidental plain display. |
| `pydantic_settings.BaseSettings` | `app.core.config.Settings` | Loads environment variables into typed settings. |
| `pydantic_settings.SettingsConfigDict` | `app.core.config.Settings` | Configures `.env` support and the `OFFERGUARD_` environment variable prefix. |

Important functions:

| Function | Purpose |
|---|---|
| `get_settings()` | Returns one cached settings object per process. |
| `Settings.allowed_upload_extension_set` | Normalizes configured upload extensions like `txt, .pdf` into `{".txt", ".pdf"}`. |

## Database and Migrations

| Library / module | Used in | Purpose |
|---|---|---|
| `sqlalchemy` | `app.db.models`, services, migrations | ORM and SQL toolkit used to map Python objects to PostgreSQL tables. |
| `sqlalchemy.orm.DeclarativeBase` | `app.db.models.Base` | Base class that owns SQLAlchemy table metadata. |
| `sqlalchemy.orm.Mapped` | ORM models | Type annotation for mapped database columns and relationships. |
| `sqlalchemy.orm.mapped_column` | ORM models | Defines SQLAlchemy mapped columns. |
| `sqlalchemy.orm.relationship` | ORM models | Defines relationship between `Document` and `ReviewJob`. |
| `sqlalchemy.ext.asyncio.create_async_engine` | `app.services.postgres` | Creates the async PostgreSQL engine. |
| `sqlalchemy.ext.asyncio.AsyncEngine` | resources and services | Type for the shared async database engine. |
| `sqlalchemy.ext.asyncio.async_sessionmaker` | document/upload services | Creates async sessions for inserting and querying rows. |
| `sqlalchemy.select` | `app.services.documents` | Builds document list/download lookup queries. |
| `sqlalchemy.text` | `app.services.postgres.check_postgres` | Runs a simple readiness query: `SELECT 1`. |
| `sqlalchemy.dialects.postgresql.UUID` | ORM models and migration | Uses PostgreSQL UUID columns. |
| `alembic` | `backend/migrations` | Versioned database schema migrations. |
| `alembic.op` | migration revision files | Creates and drops database tables. |

Important functions/classes:

| Function / class | Purpose |
|---|---|
| `create_postgres_engine(settings)` | Creates the app-wide async Postgres engine. |
| `check_postgres(engine)` | Verifies Postgres readiness. |
| `close_postgres_engine(engine)` | Disposes the database engine on shutdown. |
| `Document` | ORM model for original uploaded document metadata. |
| `ReviewJob` | ORM model for durable queued review work. |
| `DocumentUploadStatus` | String enum for upload lifecycle values. |
| `ReviewJobStatus` | String enum for review job lifecycle values. |
| `list_document_records(engine)` | Lists documents with review job status. |
| `get_document_record(engine, document_id)` | Looks up one document before download. |
| `document_record_query()` | Builds the reusable SQLAlchemy select query. |
| `to_document_record(document, review_job)` | Converts ORM rows into a service read model. |

## Object Storage

| Library / module | Used in | Purpose |
|---|---|---|
| `boto3` | `app.services.storage` | S3-compatible client used to talk to MinIO. |
| `anyio` | `app.services.storage` | Runs blocking boto3 calls in worker threads from async FastAPI code. |
| `anyio.to_thread.run_sync` | storage service | Prevents blocking the FastAPI event loop while boto3 uploads/downloads run. |

Important functions:

| Function | Purpose |
|---|---|
| `create_storage_client(settings)` | Creates the S3/MinIO client. |
| `upload_file_object(client, bucket, key, file, content_type)` | Uploads original document bytes to MinIO. |
| `get_file_object(client, bucket, key)` | Gets a stored object from MinIO for download. |

## Upload and Download Flow

| Library / module | Used in | Purpose |
|---|---|---|
| `hashlib.sha256` | `app.services.uploads` | Computes a checksum while reading uploaded file chunks. |
| `tempfile.TemporaryFile` | `app.services.uploads` | Stores validated upload bytes temporarily before sending to MinIO. |
| `urllib.parse.quote` | document download route | Safely encodes filenames in the `Content-Disposition` header. |

Important functions/classes:

| Function / class | Purpose |
|---|---|
| `get_filename_extension(filename)` | Extracts and normalizes uploaded file extension. |
| `validate_upload_extension(filename, settings)` | Rejects unsupported upload file extensions. |
| `prepare_upload_file(file, settings)` | Reads upload chunks, validates size, hashes bytes, and writes to a temp file. |
| `store_prepared_upload(prepared, settings, engine, storage_client)` | Uploads bytes to MinIO and creates `Document` plus `ReviewJob` rows. |
| `PreparedUpload` | Dataclass containing validated upload bytes and metadata. |
| `StoredDocumentUpload` | Dataclass containing persisted document/job response data. |
| `iter_storage_body(body)` | Yields MinIO object bytes for streaming download responses. |
| `upload_document(...)` | `POST /api/v1/documents` route for upload intake. |
| `list_documents(...)` | `GET /api/v1/documents` route for listing uploads. |
| `download_document(...)` | `GET /api/v1/documents/{document_id}/download` route. |

## Application Lifecycle

| Library / module | Used in | Purpose |
|---|---|---|
| `contextlib.asynccontextmanager` | `app.main.lifespan` | Defines FastAPI startup/shutdown lifecycle. |
| `collections.abc.AsyncIterator` | `app.main.lifespan` | Type annotation for async lifespan generator. |
| `dataclasses.dataclass` | resources and service read models | Creates simple typed data containers. |
| `asyncio` | `app.core.resources` | Implements startup dependency checks with timeout/retry behavior. |

Important functions/classes:

| Function / class | Purpose |
|---|---|
| `create_app()` | Builds the FastAPI app and includes API routers. |
| `lifespan(application)` | Creates resources on startup and closes them on shutdown. |
| `create_app_resources(settings)` | Creates shared Postgres, storage, and Weaviate clients. |
| `close_app_resources(resources)` | Closes shared resources. |
| `check_runtime_dependencies(resources)` | Checks dependency readiness for `/ready`. |
| `check_startup_dependencies(settings, resources)` | Waits for dependencies during startup. |
| `AppResources` | Dataclass holding app-scoped clients. |
| `DependencyCheck` | Dataclass describing startup checks. |
| `StartupDependencyError` | Error raised when startup dependencies are unavailable. |

## Weaviate Integration

| Library / module | Used in | Purpose |
|---|---|---|
| `weaviate-client` | `app.services.weaviate` | Connects to the local Weaviate vector database. |

Important functions/classes:

| Function / class | Purpose |
|---|---|
| `create_weaviate_client(settings)` | Creates a Weaviate client from configured host/ports. |
| `check_weaviate(client)` | Verifies Weaviate readiness. |
| `close_weaviate_client(client)` | Closes the Weaviate client on shutdown. |
| `WeaviateNotReadyError` | Error raised when Weaviate is not ready. |

## Logging

| Library / module | Used in | Purpose |
|---|---|---|
| `logging` | `app.observability.logging` | Standard Python logging. |
| `python-json-logger` | `app.observability.logging` | Emits structured JSON logs when configured. |

Important functions:

| Function | Purpose |
|---|---|
| `configure_logging(level, json_logs)` | Sets logging format and level. |
| `get_logger(name)` | Returns a named logger. |

## Python Built-In and Standard Library Modules

| Module / object | Used in | Purpose |
|---|---|---|
| `asyncio` | resource startup checks | Timeouts, retries, and async sleep during dependency readiness checks. |
| `collections.abc` | type annotations | Uses `Awaitable`, `Callable`, `Iterator`, and `AsyncIterator`. |
| `contextlib.asynccontextmanager` | app lifespan | Turns an async generator into a FastAPI lifespan context manager. |
| `dataclasses.dataclass` | resources/read models | Creates lightweight immutable data containers. |
| `datetime.datetime` | ORM and API models | Represents timestamps such as `created_at` and `updated_at`. |
| `enum.StrEnum` | DB status enums | Defines string-backed lifecycle statuses. |
| `functools.lru_cache` | `get_settings` | Caches settings so they are not rebuilt repeatedly. |
| `hashlib.sha256` | upload service | Computes stable document checksum. |
| `pathlib.Path` | upload service and migrations | Extracts file extensions and resolves migration paths. |
| `tempfile.TemporaryFile` | upload service | Stores upload bytes temporarily before MinIO upload. |
| `typing` | annotations | Uses `Any`, `Annotated`, `BinaryIO`, `Literal`, `Protocol`, and `cast`. |
| `urllib.parse.quote` | download route | Escapes filenames for HTTP headers. |
| `uuid.UUID` | ORM/API models | Represents document and job identifiers. |
| `uuid.uuid4` | ORM/upload service | Generates unique IDs for documents and review jobs. |
| `sys` | Alembic env | Adds `src` to Python path when Alembic runs. |
| `logging.config.fileConfig` | Alembic env | Loads Alembic logging config. |

## Test Libraries

| Library / module | Used in | Purpose |
|---|---|---|
| `pytest` | backend tests | Test runner and assertion framework. |
| `pytest.mark.asyncio` | async tests | Runs async service tests. |
| `pytest-cov` | CI test command | Measures backend test coverage. |
| `fastapi.testclient.TestClient` | integration tests | Calls FastAPI endpoints in tests without running a real server. |
| `io.BytesIO` | tests | In-memory file-like object for upload and storage tests. |
| `types.SimpleNamespace` | tests | Lightweight fake resource objects. |
| `starlette.datastructures.Headers` | upload tests | Builds realistic upload headers. |

## Frontend Libraries and Helpers

| Library / module | Used in | Purpose |
|---|---|---|
| `react` | frontend UI | Builds the upload/list/download interface. |
| `useState` | `frontend/src/App.tsx` | Stores selected file, upload state, document list, and messages. |
| `useEffect` | `frontend/src/App.tsx` | Loads existing documents when the page opens. |
| `react-dom` | `frontend/src/main.tsx` | Mounts the React app into the browser DOM. |
| `vite` | frontend build/dev server | Builds the browser app and exposes `import.meta.env`. |
| `@vitejs/plugin-react` | Vite config | Adds React support to Vite. |
| `typescript` | frontend | Type-checks frontend code. |

Important frontend helpers:

| Function | Purpose |
|---|---|
| `buildApiUrl(path)` | Combines `VITE_API_BASE_URL` with API paths. |
| `formatBytes(bytes)` | Displays document sizes in the UI. |
| `loadDocuments()` | Calls `GET /api/v1/documents` and updates the list. |
| `submit(event)` | Uploads the selected file with `POST /api/v1/documents`. |

## Infrastructure Tools

| Tool | Used in | Purpose |
|---|---|---|
| Docker Compose | `compose.yaml` | Runs frontend, backend, Postgres, Weaviate, MinIO, and migrations locally. |
| PostgreSQL | Docker service | Durable metadata and review job state. |
| MinIO | Docker service | S3-compatible storage for original uploaded documents. |
| Weaviate | Docker service | Vector database for later retrieval/indexing phases. |
| nginx | frontend container | Serves the built frontend and proxies `/api/` requests to the backend. |
| Alembic `migrate` service | Docker Compose | Runs database migrations before backend startup. |
