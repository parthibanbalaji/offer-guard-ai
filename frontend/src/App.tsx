import { FormEvent, useState } from "react";

type UploadState = "idle" | "uploading" | "complete" | "error";

export function App() {
  const [file, setFile] = useState<File | null>(null);
  const [state, setState] = useState<UploadState>("idle");
  const [message, setMessage] = useState("Select a text, Markdown, or text-based PDF offer.");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;

    const body = new FormData();
    body.append("file", file);
    setState("uploading");
    setMessage("Uploading securely…");

    try {
      const response = await fetch("/api/v1/documents", { method: "POST", body });
      if (!response.ok) throw new Error(`Upload failed (${response.status})`);
      const result = (await response.json()) as { document_id: string };
      setState("complete");
      setMessage(`Document ${result.document_id} is ready for review.`);
    } catch (error) {
      setState("error");
      setMessage(error instanceof Error ? error.message : "Upload failed");
    }
  }

  return (
    <main>
      <section className="card">
        <p className="eyebrow">AI-assisted · human-approved</p>
        <h1>Review your UAE job offer</h1>
        <p className="intro">
          Upload an offer to identify important clauses, supporting guidance, and items worth a
          closer human review.
        </p>
        <form onSubmit={submit}>
          <label className="drop-zone">
            <span>{file?.name ?? "Choose an offer document"}</span>
            <small>TXT, MD, or text-based PDF · maximum 10 MB</small>
            <input
              type="file"
              accept=".txt,.md,.pdf"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setState("idle");
              }}
            />
          </label>
          <button disabled={!file || state === "uploading"} type="submit">
            {state === "uploading" ? "Uploading…" : "Upload offer"}
          </button>
        </form>
        <p className={`status ${state}`} aria-live="polite">{message}</p>
        <p className="disclaimer">This tool provides AI-assisted review, not legal advice.</p>
      </section>
    </main>
  );
}

