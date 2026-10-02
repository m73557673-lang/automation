import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent, ChangeEvent } from "react";
import {
  AlertTriangle, BookOpen, Check, ChevronRight, FileText, LoaderCircle,
  LockKeyhole, RefreshCw, Search, ShieldCheck, Upload, X,
} from "lucide-react";
import {
  api,
  type KnowledgeBaseDocument,
  type KnowledgeBaseStatus,
  type KnowledgePassage,
  type KnowledgeSearchResponse,
} from "./api";
import "./knowledge-base.css";

const ACCEPTED_EXTENSIONS = [".txt", ".md", ".markdown"];

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function modeLabel(mode: KnowledgeBaseStatus["retrieval_mode"] | KnowledgeSearchResponse["retrieval_mode"] | null) {
  if (mode === "keyword_bm25") return "Keyword · BM25";
  if (mode === "semantic") return "Semantic";
  return "Retrieval mode unavailable";
}

function formatDate(value: string | null) {
  if (!value) return "Not indexed";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function Skeleton({ rows = 4 }: { rows?: number }) {
  return <div className="kb-load-lines" aria-label="Loading">
    {Array.from({ length: rows }, (_, index) => <div key={index}>
      <div className="kb-skeleton" style={{ width: `${index % 2 ? 68 : 86}%`, marginBottom: 9 }} />
      <div className="kb-skeleton" style={{ width: `${index % 2 ? 42 : 57}%` }} />
    </div>)}
  </div>;
}

function Empty({ title, detail, icon: Icon = BookOpen }: { title: string; detail: string; icon?: typeof BookOpen }) {
  return <div className="kb-empty">
    <div className="kb-empty-icon"><Icon size={16} aria-hidden="true" /></div>
    <strong>{title}</strong>
    {detail}
  </div>;
}

export default function KnowledgeBasePage() {
  const [status, setStatus] = useState<KnowledgeBaseStatus | null>(null);
  const [documents, setDocuments] = useState<KnowledgeBaseDocument[]>([]);
  const [totalDocuments, setTotalDocuments] = useState(0);
  const [initialLoading, setInitialLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [query, setQuery] = useState("");
  const [searchResult, setSearchResult] = useState<KnowledgeSearchResponse | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [preview, setPreview] = useState<KnowledgeBaseDocument | null>(null);
  const [previewPassage, setPreviewPassage] = useState<KnowledgePassage | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [uploadSuccess, setUploadSuccess] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [approved, setApproved] = useState(false);
  const [title, setTitle] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadBase = useCallback(async (quiet = false) => {
    if (quiet) setRefreshing(true);
    else setInitialLoading(true);
    setLoadError("");
    const [statusResponse, documentResponse] = await Promise.allSettled([
      api.knowledgeBaseStatus(),
      api.knowledgeDocuments(),
    ]);
    let failed = "";
    if (statusResponse.status === "fulfilled") setStatus(statusResponse.value);
    else failed ||= `Could not load knowledge base status: ${errorMessage(statusResponse.reason, "Request failed")}`;
    if (documentResponse.status === "fulfilled") {
      setDocuments(documentResponse.value.items);
      setTotalDocuments(documentResponse.value.total);
      setSelectedId((current) => current ?? documentResponse.value.items[0]?.id ?? null);
    } else failed ||= `Could not load documents: ${errorMessage(documentResponse.reason, "Request failed")}`;
    setLoadError(failed);
    setInitialLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => { void loadBase(); }, [loadBase]);

  const loadPreview = useCallback(async (documentId: number, chunkIndex = 0) => {
    setSelectedId(documentId);
    setPreviewLoading(true);
    setPreviewError("");
    setPreview(null);
    setPreviewPassage(null);
    const [documentResponse, passageResponse] = await Promise.allSettled([
      api.knowledgeDocument(documentId),
      api.knowledgePassage(documentId, chunkIndex),
    ]);
    if (documentResponse.status === "fulfilled") setPreview(documentResponse.value);
    else setPreviewError(`Could not load document preview: ${errorMessage(documentResponse.reason, "Request failed")}`);
    if (passageResponse.status === "fulfilled") setPreviewPassage(passageResponse.value);
    else if (documentResponse.status === "fulfilled" && documentResponse.value.indexed_chunk_count > 0) {
      setPreviewError((current) => current || `Could not load the indexed passage: ${errorMessage(passageResponse.reason, "Request failed")}`);
    }
    setPreviewLoading(false);
  }, []);

  useEffect(() => {
    if (!initialLoading && selectedId !== null && !preview && !previewLoading) void loadPreview(selectedId);
  }, [initialLoading, selectedId, preview, previewLoading, loadPreview]);

  async function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) {
      setSearchError("Enter a phrase or operational term to search.");
      setSearchResult(null);
      return;
    }
    setSearchLoading(true);
    setSearchError("");
    try {
      const result = await api.searchKnowledgePassages(trimmed);
      setSearchResult(result);
    } catch (error) {
      setSearchResult(null);
      setSearchError(`Search failed: ${errorMessage(error, "Request failed")}`);
    } finally {
      setSearchLoading(false);
    }
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0] ?? null;
    setSelectedFile(file);
    setUploadError("");
    if (file) {
      const extension = `.${file.name.split(".").pop()?.toLowerCase() ?? ""}`;
      if (!ACCEPTED_EXTENSIONS.includes(extension)) {
        setUploadError("Choose a plain text, Markdown, or .markdown file.");
        setSelectedFile(null);
        event.currentTarget.value = "";
        return;
      }
      setTitle((current) => current || file.name.replace(/\.(txt|md|markdown)$/i, "").replace(/[_-]+/g, " "));
    }
  }

  function resetUpload() {
    setUploadOpen(false);
    setUploadError("");
    setSelectedFile(null);
    setApproved(false);
    setTitle("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function submitUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const source = String(form.get("source") ?? "").trim();
    const approvedBy = String(form.get("approvedBy") ?? "").trim();
    if (!selectedFile) {
      setUploadError("Choose a supported text or Markdown file.");
      return;
    }
    if (!approved) {
      setUploadError("Confirm that you are authorized to approve this reference before submitting.");
      return;
    }
    if (!title.trim() || !source || !approvedBy) {
      setUploadError("Complete the title, source, and approver fields.");
      return;
    }
    setUploading(true);
    setUploadError("");
    try {
      const created = await api.uploadKnowledgeDocument(selectedFile, {
        title: title.trim(),
        source,
        approvedBy,
      });
      setUploadSuccess(`“${created.title}” was added. Indexing status: ${created.indexing_status}.`);
      resetUpload();
      setPreview(created);
      setPreviewPassage(null);
      setSelectedId(created.id);
      await loadBase(true);
      setPreview(created);
      setSelectedId(created.id);
    } catch (error) {
      setUploadError(errorMessage(error, "Could not upload this document."));
    } finally {
      setUploading(false);
    }
  }

  const activeMode = searchResult?.retrieval_mode ?? status?.retrieval_mode ?? null;

  return <div className="kb-page">
    <header className="kb-header">
      <div>
        <div className="eyebrow">Operational references / isolated workspace</div>
        <h1 className="kb-heading">Knowledge base</h1>
        <p className="kb-description">Find carefully sourced operational guidance while investigating. Retrieved text is reference material, not an executable control.</p>
      </div>
      <div className="kb-header-actions">
        <span className="kb-mode" title="Retrieval mode reported by the knowledge API">
          <Search size={12} aria-hidden="true" /> {modeLabel(activeMode)}
        </span>
        <button type="button" className="button small" onClick={() => void loadBase(true)} disabled={refreshing}>
          {refreshing ? <LoaderCircle size={13} /> : <RefreshCw size={13} />}
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
        <button type="button" className="button primary" onClick={() => { setUploadSuccess(""); setUploadError(""); setUploadOpen(true); }}>
          <Upload size={13} /> Add reference
        </button>
      </div>
    </header>

    {uploadSuccess && <div className="kb-success" role="status">{uploadSuccess}</div>}
    {loadError && <div className="kb-error" role="alert"><AlertTriangle size={14} />{loadError}<button type="button" onClick={() => void loadBase(true)}>Retry</button></div>}

    <section className="kb-stat-strip" aria-label="Knowledge base index status">
      <div className="kb-stat"><div className="kb-stat-label">Documents</div><div className="kb-stat-value">{status?.document_count ?? "—"}</div><div className="kb-stat-note">{totalDocuments} returned in document list</div></div>
      <div className="kb-stat"><div className="kb-stat-label">Indexed</div><div className="kb-stat-value">{status?.indexed_document_count ?? "—"}</div><div className="kb-stat-note">Documents marked indexed by API</div></div>
      <div className="kb-stat"><div className="kb-stat-label">Passage chunks</div><div className="kb-stat-value">{status?.chunk_count ?? "—"}</div><div className="kb-stat-note">Current indexed passage count</div></div>
      <div className="kb-stat"><div className="kb-stat-label">Synthetic sources</div><div className="kb-stat-value">{status?.synthetic_document_count ?? "—"}</div><div className="kb-stat-note">Synthetic documents reported by API</div></div>
    </section>

    <aside className="kb-safety">
      <LockKeyhole size={15} aria-hidden="true" />
      <span><strong>Reference only.</strong> Retrieved document text does not approve, authorize, or execute any action. This workspace contains synthetic operational material; operators must use the separate review controls for any simulated decision.</span>
    </aside>

    <div className="kb-columns">
      <section className="kb-panel" aria-labelledby="kb-documents-title">
        <div className="kb-panel-head">
          <div><div id="kb-documents-title" className="kb-panel-title">Source documents</div><div className="kb-panel-kicker">{status ? `${status.document_count} documents · ${status.indexed_document_count} indexed` : "Loading index summary"}</div></div>
          <span className="kb-badge"><FileText size={10} /> {documents.length} shown</span>
        </div>
        {initialLoading && !documents.length ? <Skeleton rows={5} /> : documents.length ? <div className="kb-doc-scroll">
          {documents.map((document) => <button
            type="button"
            className={`kb-document ${selectedId === document.id ? "selected" : ""}`}
            key={document.id}
            onClick={() => void loadPreview(document.id)}
            aria-pressed={selectedId === document.id}
          >
            <div className="kb-document-top">
              <div>
                <div className="kb-doc-title">{document.title}</div>
                <div className="kb-doc-source">{document.source} · {document.original_filename}</div>
              </div>
              <div className="kb-doc-flags">
                {document.is_synthetic && <span className="kb-badge synthetic">Synthetic</span>}
                <span className={`kb-badge ${document.indexing_status.toLowerCase() === "indexed" ? "indexed" : "pending"}`}>{document.indexing_status}</span>
              </div>
            </div>
            <div className="kb-doc-foot">
              <span>{document.indexed_chunk_count} chunks</span>
              <span>{document.approval_status}</span>
            </div>
          </button>)}
        </div> : <Empty title="No documents in the index" detail="Add an approved text or Markdown reference to make it available for retrieval." />}
      </section>

      <div className="kb-right">
        <section className="kb-panel" aria-labelledby="kb-search-title">
          <div className="kb-panel-head">
            <div><div id="kb-search-title" className="kb-panel-title">Search passages</div><div className="kb-panel-kicker">Searches return text from indexed sources</div></div>
            <span className="kb-mode"><Search size={11} /> {modeLabel(activeMode)}</span>
          </div>
          <form className="kb-search-form" onSubmit={(event) => void submitSearch(event)}>
            <label className="kb-search-field">
              <Search size={14} aria-hidden="true" />
              <input aria-label="Search the knowledge base" value={query} onChange={(event) => setQuery(event.currentTarget.value)} placeholder="Search an incident symptom, service, or procedure" />
            </label>
            <button type="submit" className="kb-search-submit" disabled={searchLoading}>
              {searchLoading ? <LoaderCircle size={13} /> : <Search size={13} />}
              {searchLoading ? "Searching…" : "Search"}
            </button>
          </form>
          {searchError && <div className="kb-error" style={{ margin: "0 13px 12px" }} role="alert"><AlertTriangle size={13} />{searchError}</div>}
          {searchLoading ? <Skeleton rows={3} /> : searchResult ? <>
            <div className="kb-results-head"><span>{searchResult.items.length} passage{searchResult.items.length === 1 ? "" : "s"} · {modeLabel(searchResult.retrieval_mode)}</span><span>“{searchResult.query}”</span></div>
            {searchResult.items.length ? <div className="kb-results-list">
              {searchResult.items.map((passage, index) => <button
                className="kb-passage"
                type="button"
                key={`${passage.document_id}-${passage.chunk_index}-${index}`}
                onClick={() => void loadPreview(passage.document_id, passage.chunk_index)}
              >
                <div className="kb-passage-meta">
                  <div>
                    <div className="kb-passage-title">{passage.title}</div>
                    <div className="kb-passage-source">{passage.source} · chunk {passage.chunk_index + 1}</div>
                  </div>
                  <div className="kb-doc-flags">
                    {typeof passage.score === "number" && <span className="kb-score">Score {passage.score.toFixed(3)}</span>}
                    {passage.is_synthetic && <span className="kb-badge synthetic">Synthetic</span>}
                  </div>
                </div>
                <p className="kb-passage-excerpt">{passage.excerpt}</p>
              </button>)}
            </div> : <Empty title="No matching passages" detail="The search completed with no passage matches. Try a different operational term." icon={Search} />}
          </> : <Empty title="Search the indexed references" detail="Results display actual passages returned by the knowledge API, including each passage's source." icon={Search} />}
        </section>

        <section className="kb-panel" aria-labelledby="kb-preview-title">
          <div className="kb-panel-head">
            <div><div id="kb-preview-title" className="kb-panel-title">Source preview</div><div className="kb-panel-kicker">Document and indexed passage detail</div></div>
            {preview && <span className="kb-badge"><ShieldCheck size={10} /> {preview.approval_status}</span>}
          </div>
          {previewLoading ? <Skeleton rows={3} /> : preview ? <div className="kb-preview-body">
            {previewError && <div className="kb-error" role="alert"><AlertTriangle size={13} />{previewError}</div>}
            <div className="kb-preview-top">
              <div>
                <h2 className="kb-preview-title">{preview.title}</h2>
                <div className="kb-preview-source">{preview.source} · {preview.original_filename}</div>
              </div>
              <span className={`kb-badge ${preview.is_synthetic ? "synthetic" : ""}`}>{preview.is_synthetic ? "Synthetic" : "Source record"}</span>
            </div>
            <div className="kb-preview-meta">
              <span className={`kb-badge ${preview.indexing_status.toLowerCase() === "indexed" ? "indexed" : "pending"}`}>{preview.indexing_status}</span>
              <span className="kb-badge">{preview.indexed_chunk_count} indexed chunks</span>
              <span className="kb-badge">Approved by {preview.approved_by || "Not specified"}</span>
            </div>
            <div className="kb-excerpt-label">Document excerpt</div>
            <blockquote className="kb-excerpt">{preview.excerpt || "No document excerpt was returned by the API."}</blockquote>
            {preview.indexed_chunk_count > 0 && <div style={{ marginTop: 12 }}>
              <div className="kb-excerpt-label">Indexed passage preview</div>
              {previewPassage ? <>
                <blockquote className="kb-excerpt">{previewPassage.excerpt}</blockquote>
                <div className="kb-chunk-row"><span>Chunk {previewPassage.chunk_index + 1} · {previewPassage.source}</span><span>{previewPassage.approval_status}</span></div>
              </> : <div className="kb-empty" style={{ padding: "12px 4px" }}>No indexed passage preview was returned.</div>}
            </div>}
            <div className="kb-chunk-row"><span>Indexed {formatDate(preview.indexed_at)}</span><span>Added {formatDate(preview.created_at)}</span></div>
          </div> : <Empty title="Select a source to inspect" detail="Choose a document or search result to load its source details and excerpt." icon={ChevronRight} />}
        </section>
      </div>
    </div>

    {uploadOpen && <div className="kb-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !uploading) resetUpload(); }}>
      <section className="kb-modal" role="dialog" aria-modal="true" aria-labelledby="kb-upload-title">
        <div className="kb-modal-head">
          <div><h2 id="kb-upload-title">Add an approved reference</h2><div className="kb-panel-kicker">Plain text and Markdown only</div></div>
          <button type="button" className="kb-icon-button" onClick={resetUpload} disabled={uploading} aria-label="Close upload form"><X size={15} /></button>
        </div>
        <form className="kb-upload-form" onSubmit={(event) => void submitUpload(event)}>
          <div className="kb-field">
            <label htmlFor="kb-file">Reference file</label>
            <input ref={fileInputRef} id="kb-file" type="file" accept=".txt,.md,.markdown,text/plain,text/markdown" onChange={onFileChange} />
            <div className="kb-file-note">This form accepts .txt, .md, and .markdown files only. Other formats are not accepted for upload here.</div>
          </div>
          <div className="kb-field"><label htmlFor="kb-title">Document title</label><input id="kb-title" name="title" value={title} onChange={(event) => setTitle(event.currentTarget.value)} required /></div>
          <div className="kb-field"><label htmlFor="kb-source">Source or owning team</label><input id="kb-source" name="source" placeholder="e.g. Platform reliability handbook" required /></div>
          <div className="kb-field"><label htmlFor="kb-approved-by">Approver name</label><input id="kb-approved-by" name="approvedBy" placeholder="Your name" required /></div>
          <label className="kb-approval-check">
            <input type="checkbox" checked={approved} onChange={(event) => setApproved(event.currentTarget.checked)} />
            <span>I confirm I am authorized to approve this reference for inclusion, and it contains no secrets or live credentials.</span>
          </label>
          {uploadError && <div className="kb-upload-error" role="alert">{uploadError}</div>}
          <div className="kb-modal-actions">
            <button type="button" className="kb-cancel" onClick={resetUpload} disabled={uploading}>Cancel</button>
            <button type="submit" className="kb-upload-submit" disabled={uploading || !approved || !selectedFile}>
              {uploading ? <LoaderCircle size={13} /> : <Check size={13} />}
              {uploading ? "Uploading…" : "Approve and upload"}
            </button>
          </div>
        </form>
      </section>
    </div>}
  </div>;
}