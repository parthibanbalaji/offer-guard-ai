import { FormEvent, useEffect, useState } from "react";

type UploadState = "idle" | "uploading" | "complete" | "error";
type LoadState = "idle" | "loading" | "ready" | "error";
type PreparationState = Record<string, "idle" | "preparing" | "complete" | "error">;
type ChunkLoadState = Record<string, "idle" | "loading" | "ready" | "error">;

type DocumentUploadResponse = {
  document_id: string;
  job_id: string;
  original_filename: string;
  media_type: string;
  size_bytes: number;
  checksum_sha256: string;
  original_storage_key: string;
  upload_status: string;
  review_job_status: string;
};

type StoredDocument = {
  document_id: string;
  job_id: string;
  original_filename: string;
  media_type: string;
  size_bytes: number;
  checksum_sha256: string;
  upload_status: string;
  review_job_status: string;
  created_at: string;
};

type DocumentPreparationResponse = {
  document_id: string;
  job_id: string;
  review_job_status: string;
  chunk_count: number;
  stored_count: number;
  indexed_count: number;
  guardrail_flags: string[];
};

type DocumentChunk = {
  id: string;
  document_id: string;
  chunk_ordinal: number;
  text: string;
  checksum_sha256: string;
  language: string;
  extraction_quality: string;
  page_number: number | null;
  section_heading: string | null;
  is_suspicious: boolean;
  guardrail_flags: string[];
  created_at: string;
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "/api";

function buildApiUrl(path: string) {
  return `${apiBaseUrl.replace(/\/$/, "")}/${path.replace(/^\//, "")}`;
}

function formatBytes(bytes: number) {
  return `${bytes.toLocaleString()} bytes`;
}

export function App() {
  const [file, setFile] = useState<File | null>(null);
  const [state, setState] = useState<UploadState>("idle");
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [message, setMessage] = useState("Select a text, Markdown, or text-based PDF offer.");
  const [document, setDocument] = useState<DocumentUploadResponse | null>(null);
  const [documents, setDocuments] = useState<StoredDocument[]>([]);
  const [preparationState, setPreparationState] = useState<PreparationState>({});
  const [preparationMessage, setPreparationMessage] = useState<Record<string, string>>({});
  const [chunkLoadState, setChunkLoadState] = useState<ChunkLoadState>({});
  const [documentChunks, setDocumentChunks] = useState<Record<string, DocumentChunk[]>>({});

  async function loadDocuments() {
    setLoadState("loading");
    try {
      const response = await fetch(buildApiUrl("/v1/documents"));
      if (!response.ok) throw new Error(`Could not load documents (${response.status})`);
      const result = (await response.json()) as StoredDocument[];
      setDocuments(result);
      setLoadState("ready");
    } catch {
      setLoadState("error");
    }
  }

  useEffect(() => {
    void loadDocuments();
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;

    const body = new FormData();
    body.append("file", file);
    setState("uploading");
    setMessage("Uploading securely...");
    setDocument(null);

    try {
      const response = await fetch(buildApiUrl("/v1/documents"), { method: "POST", body });
      if (!response.ok) throw new Error(`Upload failed (${response.status})`);
      const result = (await response.json()) as DocumentUploadResponse;
      setState("complete");
      setDocument(result);
      setMessage(`Document stored. Review job ${result.review_job_status}.`);
      await loadDocuments();
    } catch (error) {
      setState("error");
      setMessage(error instanceof Error ? error.message : "Upload failed");
    }
  }

  async function prepareReview(documentId: string) {
    setPreparationState((current) => ({ ...current, [documentId]: "preparing" }));
    setPreparationMessage((current) => ({ ...current, [documentId]: "Preparing review..." }));

    try {
      const response = await fetch(buildApiUrl(`/v1/documents/${documentId}/prepare`), {
        method: "POST",
      });
      if (!response.ok) throw new Error(`Could not prepare review (${response.status})`);
      const result = (await response.json()) as DocumentPreparationResponse;
      setPreparationState((current) => ({ ...current, [documentId]: "complete" }));
      setPreparationMessage((current) => ({
        ...current,
        [documentId]: `Stored ${result.stored_count} chunks; indexed ${result.indexed_count}.`,
      }));
      await loadDocuments();
    } catch (error) {
      setPreparationState((current) => ({ ...current, [documentId]: "error" }));
      setPreparationMessage((current) => ({
        ...current,
        [documentId]: error instanceof Error ? error.message : "Could not prepare review",
      }));
    }
  }

  async function loadChunks(documentId: string) {
    if (chunkLoadState[documentId] === "ready") {
      setChunkLoadState((current) => ({ ...current, [documentId]: "idle" }));
      return;
    }

    setChunkLoadState((current) => ({ ...current, [documentId]: "loading" }));
    try {
      const response = await fetch(buildApiUrl(`/v1/documents/${documentId}/chunks`));
      if (!response.ok) throw new Error(`Could not load chunks (${response.status})`);
      const result = (await response.json()) as DocumentChunk[];
      setDocumentChunks((current) => ({ ...current, [documentId]: result }));
      setChunkLoadState((current) => ({ ...current, [documentId]: "ready" }));
    } catch {
      setChunkLoadState((current) => ({ ...current, [documentId]: "error" }));
    }
  }

  return (
    <main>
      <section className="card">
        <p className="eyebrow">AI-assisted / human-approved</p>
        <h1>Review your UAE job offer</h1>
        <p className="intro">
          Upload an offer to identify important clauses, supporting guidance, and items worth a
          closer human review.
        </p>
        <form onSubmit={submit}>
          <label className="drop-zone">
            <span>{file?.name ?? "Choose an offer document"}</span>
            <small>TXT, MD, or text-based PDF / maximum 10 MB</small>
            <input
              type="file"
              accept=".txt,.md,.pdf"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setState("idle");
                setDocument(null);
              }}
            />
          </label>
          <button disabled={!file || state === "uploading"} type="submit">
            {state === "uploading" ? "Uploading..." : "Upload offer"}
          </button>
        </form>
        <p className={`status ${state}`} aria-live="polite">
          {message}
        </p>
        {document ? (
          <section className="document-summary" aria-label="Uploaded document">
            <div>
              <span>Document</span>
              <strong>{document.original_filename}</strong>
            </div>
            <div>
              <span>Upload status</span>
              <strong>{document.upload_status}</strong>
            </div>
            <div>
              <span>Review job</span>
              <strong>{document.review_job_status}</strong>
            </div>
            <div>
              <span>Size</span>
              <strong>{formatBytes(document.size_bytes)}</strong>
            </div>
            <div className="wide">
              <span>Document ID</span>
              <code>{document.document_id}</code>
            </div>
            <div className="wide">
              <span>Job ID</span>
              <code>{document.job_id}</code>
            </div>
            <div className="wide">
              <span>Checksum</span>
              <code>{document.checksum_sha256}</code>
            </div>
          </section>
        ) : null}

        <section className="documents-panel" aria-label="Stored documents">
          <div className="panel-heading">
            <h2>Uploaded documents</h2>
            <button className="secondary" type="button" onClick={() => void loadDocuments()}>
              Refresh
            </button>
          </div>
          {loadState === "loading" ? <p className="muted">Loading documents...</p> : null}
          {loadState === "error" ? (
            <p className="status error">Could not load uploaded documents.</p>
          ) : null}
          {loadState !== "loading" && documents.length === 0 ? (
            <p className="muted">No documents uploaded yet.</p>
          ) : null}
          {documents.length > 0 ? (
            <div className="documents-list">
              {documents.map((item) => (
                <article className="document-row" key={item.document_id}>
                  <div>
                    <strong>{item.original_filename}</strong>
                    <span>{formatBytes(item.size_bytes)}</span>
                  </div>
                  <div>
                    <span>Upload: {item.upload_status}</span>
                    <span>Job: {item.review_job_status}</span>
                    {preparationMessage[item.document_id] ? (
                      <span className={`preparation-note ${preparationState[item.document_id]}`}>
                        {preparationMessage[item.document_id]}
                      </span>
                    ) : null}
                  </div>
                  <div className="document-actions">
                    <button
                      className="secondary"
                      disabled={preparationState[item.document_id] === "preparing"}
                      type="button"
                      onClick={() => void prepareReview(item.document_id)}
                    >
                      {preparationState[item.document_id] === "preparing"
                        ? "Preparing..."
                        : "Prepare review"}
                    </button>
                    <button
                      className="secondary"
                      disabled={chunkLoadState[item.document_id] === "loading"}
                      type="button"
                      onClick={() => void loadChunks(item.document_id)}
                    >
                      {chunkLoadState[item.document_id] === "ready" ? "Hide chunks" : "View chunks"}
                    </button>
                    <a href={buildApiUrl(`/v1/documents/${item.document_id}/download`)}>
                      Download
                    </a>
                  </div>
                  {chunkLoadState[item.document_id] === "error" ? (
                    <p className="status error wide">Could not load chunks.</p>
                  ) : null}
                  {chunkLoadState[item.document_id] === "ready" ? (
                    <div className="chunk-list">
                      {(documentChunks[item.document_id] ?? []).length === 0 ? (
                        <p className="muted">No chunks stored yet.</p>
                      ) : null}
                      {(documentChunks[item.document_id] ?? []).map((chunk) => (
                        <section className="chunk-row" key={chunk.id}>
                          <div>
                            <strong>Chunk {chunk.chunk_ordinal + 1}</strong>
                            <span>
                              {chunk.page_number ? `Page ${chunk.page_number}` : "No page"} /{" "}
                              {chunk.section_heading ?? "No section"}
                            </span>
                          </div>
                          <p>{chunk.text}</p>
                          <code>{chunk.checksum_sha256}</code>
                          {chunk.is_suspicious ? (
                            <span className="preparation-note error">
                              Suspicious: {chunk.guardrail_flags.join(", ")}
                            </span>
                          ) : null}
                        </section>
                      ))}
                    </div>
                  ) : null}
                </article>
              ))}
            </div>
          ) : null}
        </section>
        <p className="disclaimer">This tool provides AI-assisted review, not legal advice.</p>
      </section>
    </main>
  );
}
