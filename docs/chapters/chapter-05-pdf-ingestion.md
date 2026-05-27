# Chapter 5: The Document Intelligence Ingestion Pipeline

In Chapter 4 you built two storage systems on SAP HANA Cloud: a vector table that answers fuzzy semantic questions and a Knowledge Graph that answers precise factual ones. Both are powerful in isolation. The missing piece is the plumbing — the code that takes any PDF file uploaded against an SAP Material Number and feeds both systems at the same time, cleanly, without one pipeline blocking the other, and without leaving the user waiting at a spinning upload button.

That is what this chapter builds. By the end of it you will have `agents/srv/doc_srv.py`, a production-quality ingestion service that receives a PDF upload, immediately acknowledges the request, and runs two threads simultaneously — one chunking and embedding text into the vector store, the other extracting structured triples into the Knowledge Graph. The caller gets a response in milliseconds. The heavy lifting happens asynchronously.

The pipeline is document-type agnostic at the infrastructure level. Whether the uploaded file is an MSDS, a purchase order, a batch certificate, or a quality inspection report, the same dual-thread architecture applies. The vector pipeline always chunks, embeds, and stores to HANA REAL_VECTOR. The KG pipeline always calls Gemini and stores triples via SPARQL. The only thing that varies per document type is the Gemini prompt used for triple extraction — a single configuration point that determines what structured knowledge the pipeline extracts from that document class.

There is a subtlety that trips up almost every developer the first time they write multithreaded database code in Python: connection sharing. A single HANA connection is not thread-safe. If Thread 1 and Thread 2 share one connection object, you will see intermittent failures that look like data corruption, because they are. This chapter explains why that happens, how Python's `threading.local()` solves it, and how to wire the solution correctly inside a FastAPI background task.

---

## 5.1 The dual-pipeline architecture

The fundamental design choice in this chapter is that every PDF upload triggers exactly two independent pipelines, running in parallel, with no coordination between them except that they both read from the same source file.

![Dual-Pipeline Ingestion Architecture](docs/screenshots/diagrams/06-dual-pipeline-architecture.png)
*Figure 5.1: The Document Intelligence Ingestion Pipeline. Thread 1 (left) chunks the PDF text and stores embeddings in MSDS_VECTORS. Thread 2 (right) sends full text to Gemini for triple extraction and stores the result as a named RDF graph in HANA. Both threads update their own status field on completion. The FastAPI endpoint returns immediately, before either thread has finished.*

### 5.1.1 Why process both in parallel?

The two pipelines are genuinely independent operations. The vector pipeline calls `text-embedding-004` to generate embeddings for each chunk. The KG pipeline calls Gemini 2.5 Flash to generate RDF triples from the full document text. Neither result depends on the other. There is no reason to run them sequentially — doing so would simply double ingestion time.

| Dimension | Vector pipeline | KG pipeline |
|---|---|---|
| Input to pipeline | Chunks (500 tokens each) | Full document text |
| External API call | `text-embedding-004` (many calls) | Gemini 2.5 Flash (one call) |
| HANA operation | Many `INSERT` statements | One `SPARQL_EXECUTE` insert |
| Failure mode | Can fail on any chunk | Atomic — succeeds or fails entirely |

On a 30-page batch quality certificate or MSDS document the difference is measurable. Embedding 60 chunks against the Vertex AI API takes roughly 8–12 seconds. Calling Gemini 2.5 Flash for triple extraction from the same document takes 3–6 seconds. Sequential: 14–18 seconds. Parallel: 8–12 seconds (the slower pipeline dominates). The improvement compounds across every document uploaded across the platform.

`ThreadPoolExecutor(max_workers=2)` is the implementation mechanism. It creates exactly two OS threads within the FastAPI process — one for each pipeline. This is true parallelism: the embedding API calls in Thread 1 and the Gemini call in Thread 2 execute concurrently, sharing nothing except the temp file path.

### 5.1.2 The fire-and-forget pattern

The CAP Fiori UI calls `POST /process-upload` and needs a fast response. A user who clicks the upload button should not wait 10–15 seconds staring at a loading indicator — that is an unacceptable user experience for an enterprise application.

The solution is fire-and-forget. The upload endpoint returns `202 Accepted` with `{"status": "processing"}` immediately after spawning the background threads — before either pipeline has done any significant work. The HTTP connection closes. The threads run independently.

The CAP service then polls `GET /status/{material_number}` every 3 seconds. The Fiori UI updates two status indicators — one for vector ingestion, one for KG ingestion — based on what the status endpoint returns. When both reach a terminal state (`DONE` or `ERROR`), polling stops and the UI updates the document card.

This decoupling is critical for BTP Cloud Foundry deployments. HTTP request timeouts on CF are typically 60 seconds. A large document (100+ pages) can take 90 seconds to process. Without fire-and-forget, those documents would always fail at the HTTP layer, even when the actual processing succeeded.

Status is persisted in HANA — in the `MSDS_DOCUMENTS` table — not in memory. This means status survives a server restart. If the CF instance is recycled while processing is in flight, the status row already exists in HANA showing `PROCESSING`. A monitoring query can find and retry stalled documents without reading log files.

---

## 5.2 PDF text extraction with PyMuPDF

PyMuPDF (import name `fitz`) is a Python binding for the MuPDF rendering library. It is the fastest Python-accessible PDF parser available and handles the dirty reality of enterprise PDFs well: multi-column layouts, embedded tables, rotated pages, and the mixture of text layers and bitmap content that characterises scanned regulatory documents.

Add it to `agents/requirements.txt`:

```
PyMuPDF==1.24.3
```

The basic extraction pattern is three lines:

```python
import fitz  # PyMuPDF

def extract_text(pdf_path: str) -> str:
    doc = fitz.open(pdf_path)
    text = "".join(page.get_text() for page in doc)
    doc.close()
    return text
```

`page.get_text()` with no arguments returns the page's text content in reading order, with word-level coordinates used internally to reconstruct flow. For most material documents this produces clean, paragraph-structured text. For scanned PDFs (no text layer) it returns an empty string — handled below.

### 5.2.1 Extracting with metadata

In `agents/srv/doc_srv.py` we use a slightly richer version that preserves page boundaries:

```python
import fitz
from typing import Optional

def extract_pdf_text(path: str) -> tuple[str, int]:
    """
    Returns (full_text, page_count).
    Raises ValueError if the PDF contains no extractable text layer.
    """
    doc = fitz.open(path)
    pages = []
    for page in doc:
        page_text = page.get_text().strip()
        if page_text:
            pages.append(page_text)
    doc.close()

    if not pages:
        raise ValueError(
            f"PDF '{path}' contains no extractable text. "
            "It may be a scanned image-only document."
        )

    return "\n\n".join(pages), len(pages)
```

The `ValueError` is important. If a scanned PDF arrives and we silently extract an empty string, the vector pipeline produces zero embeddings and the KG pipeline sends an empty prompt to Gemini. Both pipelines appear to succeed, but the document is never searchable. Raising early surfaces the problem immediately and sets both status columns to `ERROR` with a meaningful message — visible to operators without reading log files.

> **Warning:** PyMuPDF's `get_text()` preserves hyphenation artifacts from PDF layout. Words broken across lines (e.g., "flamma-" + newline + "ble") will appear as a hyphenated pair in the extracted string. For material documents this rarely causes problems because the affected words are typically in multi-column document tables, but if your documents have heavy hyphenation, consider a post-processing step: `text = re.sub(r'-\n', '', text)`.

### 5.2.2 Handling upload files in FastAPI

FastAPI receives uploaded files as `UploadFile` objects. We need to write the file to disk before passing the path to PyMuPDF, because `fitz.open()` accepts file paths or byte buffers — and the byte buffer approach for large PDFs can exhaust memory. The safest pattern uses Python's `tempfile`:

```python
import tempfile
import shutil
from fastapi import UploadFile

async def save_upload(upload: UploadFile) -> str:
    """Saves UploadFile to a temp file. Returns the path. Caller must delete."""
    suffix = ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(upload.file, tmp)
        return tmp.name
```

Using `delete=False` gives us a path we can pass to background threads. We delete the file ourselves after both threads complete.

---

## 5.3 Chunking strategy for vector search

The vector pipeline does not process the full document text as a single unit. A 30-page material document contains 8,000–12,000 words. Embedding that as one unit would produce a single 768-dimensional vector that averages the meaning of everything — test results, storage requirements, delivery conditions, specification tables — into an undifferentiated blob. Cosine similarity against that vector would return the document for almost any question. Precision would be zero.

The answer is chunking: splitting the document into smaller, semantically coherent pieces and embedding each independently. The cosine search then retrieves the specific chunks most relevant to a question, not the whole document.

### 5.3.1 Our chunking parameters

We use three parameters:

| Parameter | Value | Rationale |
|---|---|---|
| Chunk size | 500 tokens | Roughly 375 words. Large enough to preserve context around a fact, small enough for the vector to encode a focused meaning. |
| Overlap | 50 tokens | Approximately one sentence. Prevents a fact from being split exactly at a chunk boundary and disappearing from both adjacent chunks. |
| Split boundary | Sentence end | Never cut in the middle of a sentence. A half-sentence changes the meaning of the embedding. |

The `text-embedding-004` model from Vertex AI accepts up to 3,072 tokens per input. Our 500-token chunks are well within that limit, which gives us room to include a prefix that grounds the embedding with document metadata:

```
Material: BATCH-QC-MAT-001\n\n<chunk text>
```

Adding the material name to every chunk significantly improves retrieval accuracy for multi-document queries. Without it, a chunk about "tensile test" could match any of dozens of batch certificates.

This prefix approach is also what makes the vector pipeline document-type agnostic. The same chunker, with the same parameters, handles an MSDS equally well as a purchase order or a quality inspection certificate — the material prefix ensures retrieved chunks are always scoped to the correct document.

### 5.3.2 The chunker function

```python
import re
from typing import Generator

def chunk_text(
    text: str,
    material_name: str,
    chunk_tokens: int = 500,
    overlap_tokens: int = 50,
) -> Generator[str, None, None]:
    """
    Yields overlapping chunks of approximately chunk_tokens each,
    split on sentence boundaries. Prefixes each chunk with material_name.

    Token estimation: 1 token ≈ 0.75 words (English prose).
    """
    chunk_words   = int(chunk_tokens  * 0.75)
    overlap_words = int(overlap_tokens * 0.75)

    # Split on sentence-ending punctuation followed by whitespace
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())

    current_chunk: list[str] = []
    current_count: int       = 0
    prefix = f"Material: {material_name}\n\n"

    for sentence in sentences:
        word_count = len(sentence.split())
        if current_count + word_count > chunk_words and current_chunk:
            yield prefix + " ".join(current_chunk)
            # Keep the last overlap_words words as context for the next chunk
            overlap_start = max(0, len(current_chunk) - overlap_words)
            current_chunk = current_chunk[overlap_start:]
            current_count = sum(len(s.split()) for s in current_chunk)
        current_chunk.append(sentence)
        current_count += word_count

    # Emit the final partial chunk if it has content
    if current_chunk:
        yield prefix + " ".join(current_chunk)
```

> **Tip:** This chunker uses a word-count approximation for token count (`1 token ≈ 0.75 words`). For production use, replace the approximation with the `tiktoken` library: `len(tiktoken.encoding_for_model("text-embedding-ada-002").encode(text))`. The approximation is accurate enough for material documents, where prose density is fairly uniform.

### 5.3.3 Why the KG pipeline does not chunk

The Knowledge Graph pipeline receives the **full document text**, not chunks. This is a deliberate asymmetry.

Gemini's triple extraction works best when it can see the entire document context. A certificate number (QC-CERT-44781) might appear in the batch header section of a quality certificate. The material name appears in the header. The certifying laboratory appears in the test results section. If we feed Gemini a chunk that contains only the test results section, it cannot associate the certificate number with the material and certifying lab, because those context clues are in different sections.

For the KG pipeline, the goal is to extract a small number of high-precision facts (typically 5–15 triples per document). Gemini 2.5 Flash can easily handle 10,000 words in a single prompt, so there is no technical reason to chunk. The full-document approach produces far better triple quality.

The KG extraction prompt is the single configuration point that varies per document type. An invoice prompt instructs it to extract vendor, line items, and payment terms. A batch certificate prompt extracts test results, pass/fail verdicts, and certifying laboratory. A regulatory document prompt extracts hazard codes, exposure limits, and precaution statements. The chunker code and the SPARQL insert code remain identical across all document types.

---

## 5.4 Thread-local HANA connections

This section addresses the most important implementation detail in this chapter. Get it wrong and you will see intermittent `hdbcli` errors that are extremely difficult to debug. Understand it and the threading model becomes straightforward.

### 5.4.1 Why connections cannot be shared across threads

The `hdbcli` driver maintains a stateful protocol session on each connection object. Internally, a connection tracks the current transaction state, pending fetch buffers for open cursors, and the sequence of SQL commands in the current batch. When two threads share a single connection and execute concurrently, they can each call `cursor.execute()` at the same time. The driver serialises the calls — but by the time the second call returns, the first thread may have already called `cursor.fetchall()` on a different cursor that was internally sharing the same fetch buffer. The result is that one thread reads the other thread's data, or gets an exception, or silently gets an empty result.

None of these failures are deterministic. They depend on exact scheduling and timing. This is the canonical definition of a race condition.

> **Warning:** Never share an `hdbcli` connection across threads. The `hdbcli` documentation explicitly states that connection objects are not thread-safe. This applies to most database drivers, not just HANA. When in doubt, assume a connection is single-threaded.

### 5.4.2 The `threading.local()` solution

Python's `threading.local()` provides a simple mechanism: an object where each attribute access returns a different value depending on which thread is reading it. When Thread 1 sets `_local.conn = hana_db.connect()`, Thread 2 sees `_local.conn` as unset. Each thread must initialise its own value.

Here is the pattern we use in `agents/srv/doc_srv.py`:

```python
import threading
from hdbcli import dbapi

_thread_local = threading.local()

def get_hana_connection() -> dbapi.Connection:
    """
    Returns a HANA connection for the current thread.
    Creates one on first access; reuses it on subsequent calls within the same thread.
    """
    if not hasattr(_thread_local, "conn") or _thread_local.conn is None:
        _thread_local.conn = dbapi.connect(
            address=os.environ["HANA_HOST"],
            port=int(os.environ["HANA_PORT"]),
            user=os.environ["HANA_USER"],
            password=os.environ["HANA_PASSWORD"],
        )
    return _thread_local.conn

def close_thread_connection() -> None:
    """Closes and clears the connection for the current thread."""
    if hasattr(_thread_local, "conn") and _thread_local.conn is not None:
        try:
            _thread_local.conn.close()
        except Exception:
            pass
        _thread_local.conn = None
```

The `get_hana_connection()` function is called at the start of each thread function. If the thread is new, it creates a fresh connection. If the same thread somehow reuses its worker slot (which can happen with thread pools), it reuses the existing connection — which is safe because it is still the same thread.

> **Note:** The thread pool created by `ThreadPoolExecutor` may reuse worker threads across multiple task submissions if the executor stays alive. In our implementation, we create a fresh `ThreadPoolExecutor` for each upload, so each worker thread is new and its `threading.local()` storage is empty. If you ever switch to a long-lived executor, add a health check before reusing a connection: `_thread_local.conn.isconnected()`.

---

## 5.5 The ingestion flow in detail

Now we have all the pieces. Let us trace the full execution path for a single document upload from the CAP Fiori UI through to both HANA stores.

### 5.5.1 The upload endpoint

```python
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse
import asyncio, os, re, tempfile, shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

app = FastAPI()

@app.post("/process-upload")
async def process_upload(
    file: UploadFile = File(...),
    materialNumber: str = Form(...),
    materialName: str   = Form(...),
):
    if not re.match(r'^[A-Za-z0-9_-]+$', materialNumber):
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid materialNumber. Use only letters, digits, hyphens, underscores."}
        )

    # Write upload to a temp file so background threads can access it by path
    loop = asyncio.get_event_loop()
    tmp_path = await loop.run_in_executor(None, _save_upload_sync, file)

    # Mark both pipelines as PROCESSING in HANA before returning
    _mark_processing(materialNumber)

    # Hand off to background threads — fire and forget
    loop.run_in_executor(None, _run_dual_pipeline, tmp_path, materialNumber, materialName)

    return {"status": "processing", "materialNumber": materialNumber}
```

The material number validation — `^[A-Za-z0-9_-]+$` — is enforced at every entry point in the application. This is SPARQL injection prevention: a material number like `MAT-001> } INSERT { <evil> }` would pass a naive check but break out of a SPARQL query. The regex ensures the material number can only contain characters that are safe to embed in an IRI.

Three things happen before the response is sent: the uploaded file is written to a temp path, `_mark_processing()` sets both status fields to `'PROCESSING'` in HANA, and `_run_dual_pipeline()` is submitted to an executor — it runs *after* the response returns.

### 5.5.2 The dual-pipeline orchestrator

```python
def _run_dual_pipeline(
    tmp_path: str,
    material_number: str,
    material_name: str,
) -> None:
    """
    Runs vector and KG pipelines in parallel.
    Called in a background thread — must not raise unhandled exceptions.
    """
    try:
        text, page_count = extract_pdf_text(tmp_path)
    except ValueError as exc:
        # PDF has no text layer — fail both pipelines immediately
        _mark_vector_status(material_number, "ERROR", str(exc))
        _mark_kg_status(    material_number, "ERROR", str(exc))
        os.unlink(tmp_path)
        return

    vector_error = None
    kg_error     = None

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_vector = executor.submit(_vector_pipeline, text, material_number, material_name)
        future_kg     = executor.submit(_kg_pipeline, text, material_number)

        for future in as_completed([future_vector, future_kg]):
            try:
                future.result()
            except Exception as exc:
                if future is future_vector:
                    vector_error = str(exc)
                else:
                    kg_error = str(exc)

    # Update statuses independently — one failure does not mask the other
    _mark_vector_status(material_number, "ERROR" if vector_error else "DONE", vector_error)
    _mark_kg_status(    material_number, "ERROR" if kg_error     else "DONE", kg_error)

    try:
        os.unlink(tmp_path)
    except OSError:
        pass
```

The `with ThreadPoolExecutor(max_workers=2)` block creates exactly two worker threads. `as_completed()` yields futures as they finish; we capture any exception from each without letting it propagate, so a failure in one pipeline does not cancel the other. Both pipelines are given the opportunity to complete, succeed, or fail independently.

### 5.5.3 Thread 1 — the vector pipeline

```python
from agents.srv.vector_srv import embed_text, upsert_vectors

def _vector_pipeline(
    text: str,
    material_number: str,
    material_name: str,
) -> None:
    conn   = get_hana_connection()
    chunks = list(chunk_text(text, material_name))

    for i, chunk in enumerate(chunks):
        embedding = embed_text(chunk)          # Vertex AI text-embedding-004
        upsert_vectors(
            conn=conn,
            material_number=material_number,
            chunk_index=i,
            chunk_text=chunk,
            embedding=embedding,               # list[float], length 768
        )

    close_thread_connection()
```

`embed_text()` calls `text-embedding-004` through the Vertex AI Python SDK. For a 30-page document with 60 chunks, this function makes 60 sequential API calls, each taking roughly 150–200 ms — approximately 10–12 seconds total.

`upsert_vectors()` executes a SQL `UPSERT` on the `MSDS_VECTORS` table, using `(material_number, chunk_index)` as the key. Re-uploading a document replaces its existing vectors cleanly. The `MSDS_VECTORS` table serves all document types on the platform — an invoice chunk and an MSDS chunk differ only in their content and the material number they are associated with.

> **Tip:** For large document batches, consider batching the embedding calls. The `text-embedding-004` endpoint accepts up to 250 texts in a single request. Instead of 60 individual calls for 60 chunks, one batched call returns all 60 embeddings at once. The latency drops from ~10 seconds to ~1.5 seconds for the embed step. Batching is shown in Appendix C.

### 5.5.4 Thread 2 — the Knowledge Graph pipeline

```python
from agents.srv.kg_srv import extract_triples_from_text, insert_triples

def _kg_pipeline(text: str, material_number: str) -> None:
    conn    = get_hana_connection()
    triples = extract_triples_from_text(text, material_number)

    if not triples:
        raise ValueError(
            f"Zero triples extracted for '{material_number}'. "
            "Check document quality and ontology alignment."
        )

    insert_triples(conn=conn, material_number=material_number, triples=triples)
    close_thread_connection()
```

`extract_triples_from_text()` is the Gemini 2.5 Flash extraction function built in Chapter 4. It sends the full text with a structured prompt that includes the ontology predicates and asks for JSON output. `insert_triples()` builds a SPARQL `INSERT DATA` query and calls `SPARQL_EXECUTE` on the HANA connection. The resulting triples are stored in the named graph `MSDS_Graph/MAT-XXX` under the `msds.kg` namespace.

The "zero triples" check is deliberate. A successful Gemini call that returns no triples is worse than a clean failure — the document would appear as `kgStatus = 'DONE'` to the user but produce no graph query results. Raising `ValueError` here sets `kgStatus = 'ERROR'`, which makes the problem visible in the CAP UI and queryable in the `MSDS_DOCUMENTS` table.

---

## 5.6 Status tracking

The CAP Fiori UI needs to know when ingestion is complete and what the result counts are. The UI polls `GET /status/{materialNumber}` every 3 seconds until both pipelines report a terminal state. The status data it receives comes entirely from the `MSDS_DOCUMENTS` table in HANA.

### 5.6.1 The MSDS_DOCUMENTS table and its role

`MSDS_DOCUMENTS` is the control plane of the ingestion pipeline. Every upload creates or updates a row here. The CAP OData service reads from this table to populate the document list in the Fiori UI — the `triples` count (how many KG facts were extracted), the `vectors` count (how many chunks were embedded), and the status indicators for each pipeline all come from this table.

| Column | Tracks | Values |
|---|---|---|
| `STATUS` | KG pipeline | `PROCESSING`, `DONE`, `ERROR` |
| `VECTOR_STATUS` | Vector pipeline | `PROCESSING`, `DONE`, `ERROR` |
| `KG_ERROR` | KG failure reason | NULL or error message |
| `VECTOR_ERROR` | Vector failure reason | NULL or error message |

Using two separate status columns rather than one combined status allows the UI to show partial progress — "Vector: DONE, KG: PROCESSING..." — and makes it possible to retry only the failed pipeline without re-running the successful one.

### 5.6.2 Status helper functions

```python
def _mark_processing(material_number: str) -> None:
    conn = get_hana_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPSERT MSDS_DOCUMENTS (MATERIAL_NUMBER, STATUS, VECTOR_STATUS, CREATED_AT)
        VALUES (?, 'PROCESSING', 'PROCESSING', NOW())
        WITH PRIMARY KEY
    """, (material_number,))
    conn.commit()
    cursor.close()
    close_thread_connection()

def _mark_vector_status(material_number: str, status: str, error_message=None) -> None:
    conn = get_hana_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE MSDS_DOCUMENTS
        SET VECTOR_STATUS = ?, VECTOR_ERROR = ?, UPDATED_AT = NOW()
        WHERE MATERIAL_NUMBER = ?
    """, (status, error_message, material_number))
    conn.commit()
    cursor.close()
    close_thread_connection()

def _mark_kg_status(material_number: str, status: str, error_message=None) -> None:
    conn = get_hana_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE MSDS_DOCUMENTS
        SET STATUS = ?, KG_ERROR = ?, UPDATED_AT = NOW()
        WHERE MATERIAL_NUMBER = ?
    """, (status, error_message, material_number))
    conn.commit()
    cursor.close()
    close_thread_connection()
```

### 5.6.3 The status endpoint

```python
@app.get("/status/{material_number}")
def get_status(material_number: str):
    if not re.match(r'^[A-Za-z0-9_-]+$', material_number):
        return JSONResponse(status_code=400, content={"error": "Invalid materialNumber"})

    conn = get_hana_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT STATUS, VECTOR_STATUS, KG_ERROR, VECTOR_ERROR, UPDATED_AT
        FROM   MSDS_DOCUMENTS
        WHERE  MATERIAL_NUMBER = ?
    """, (material_number,))
    row = cursor.fetchone()
    cursor.close()
    close_thread_connection()

    if not row:
        return JSONResponse(status_code=404, content={"error": "Material not found"})

    kg_status, vector_status, kg_error, vector_error, updated_at = row
    return {
        "materialNumber": material_number,
        "kgStatus":       kg_status,
        "vectorStatus":   vector_status,
        "kgError":        kg_error,
        "vectorError":    vector_error,
        "updatedAt":      str(updated_at),
        "complete":       kg_status in ("DONE", "ERROR") and
                          vector_status in ("DONE", "ERROR"),
    }
```

The `complete` boolean is the sentinel the CAP service uses to stop polling. If `complete` is `true` but either status is `ERROR`, the Fiori UI shows an error banner with the error message but does not block navigation — the user can still query against whichever pipeline succeeded.

---

## 5.7 Error handling — what happens when one pipeline fails

The most important design property of this ingestion service is **error isolation**: a failure in one pipeline does not affect the other.

| Failure | What happens | Status in HANA |
|---|---|---|
| PDF has no text layer | Both pipelines fail before threads start | Both `ERROR`, same error message |
| Vertex AI embedding API down | `_vector_pipeline` raises; `_kg_pipeline` continues | `vectorStatus = ERROR`, `kgStatus = DONE` |
| Gemini triple extraction returns empty | `_kg_pipeline` raises; `_vector_pipeline` has already completed | `vectorStatus = DONE`, `kgStatus = ERROR` |
| HANA connection fails in one thread | Affected thread raises; other thread uses its own connection | Independent `ERROR` / `DONE` |

Scenario 2 deserves attention because it reflects a real operational condition. When a Vertex AI service outage occurs, every embedding call will fail. If error propagation were allowed, the `ThreadPoolExecutor` would cancel the KG future when the vector future raises — and the document would have no graph knowledge despite the Gemini extraction succeeding. The `try/except` wrapper in `as_completed()` prevents that cancellation.

Persisting error messages in the `KG_ERROR` and `VECTOR_ERROR` columns means operators can run `SELECT MATERIAL_NUMBER, KG_ERROR FROM MSDS_DOCUMENTS WHERE STATUS = 'ERROR'` to get a triage list without reading log files. This is the operational advantage of storing status in HANA rather than in application logs.

---

## 5.8 Testing — upload five material documents

### 5.8.1 Start the service

```bash
cd agents
source .venv/bin/activate
uvicorn main:app --reload --port 8000
```

### 5.8.2 Upload the first document

```bash
curl -s -X POST http://localhost:8000/process-upload \
     -F "file=@/path/to/batch-cert-001.pdf" \
     -F "materialNumber=MAT-001" \
     -F "materialName=BATCH-QC-MAT-001"
```

Expected response (within 200 ms):

```json
{"status": "processing", "materialNumber": "MAT-001"}
```

### 5.8.3 Poll for completion

```bash
watch -n3 'curl -s http://localhost:8000/status/MAT-001 | python3 -m json.tool'
```

After 8–15 seconds:

```json
{
    "materialNumber": "MAT-001",
    "kgStatus": "DONE",
    "vectorStatus": "DONE",
    "kgError": null,
    "vectorError": null,
    "updatedAt": "2026-05-27 09:31:17.447",
    "complete": true
}
```

### 5.8.4 Verify the vector store

```sql
SELECT
    CHUNK_INDEX,
    LEFT(CHUNK_TEXT, 80) AS CHUNK_PREVIEW,
    CARDINALITY(EMBEDDING) AS VECTOR_DIM
FROM MSDS_VECTORS
WHERE MATERIAL_NUMBER = 'MAT-001'
ORDER BY CHUNK_INDEX;
```

Expected: every row has `VECTOR_DIM = 768`.

### 5.8.5 Verify the Knowledge Graph

```python
from hdbcli import dbapi
import os

conn = dbapi.connect(
    address=os.environ["HANA_HOST"],
    port=int(os.environ["HANA_PORT"]),
    user=os.environ["HANA_USER"],
    password=os.environ["HANA_PASSWORD"],
)
cursor = conn.cursor()

sparql = """
PREFIX msds: <http://msds.knowledge-graph.org/ontology/>
SELECT ?predicate ?object
WHERE {
  GRAPH <http://msds.knowledge-graph.org/MSDS_Graph/MAT-001> {
    <http://msds.knowledge-graph.org/material/MAT-001> ?predicate ?object .
  }
}
"""

cursor.callproc("SPARQL_EXECUTE", [sparql, None, 1000, None, None])
rows = cursor.fetchall()
for row in rows:
    print(row)
```

Expected output:

```
('http://msds.knowledge-graph.org/ontology#certifiedBy',      'ACME Steel AG')
('http://msds.knowledge-graph.org/ontology#certificateNumber','QC-CERT-44781')
('http://msds.knowledge-graph.org/ontology#testResult',       'ISO 6892-1 tensile test')
('http://msds.knowledge-graph.org/ontology#certifyingLab',    'Bureau Veritas Testing GmbH')
('http://msds.knowledge-graph.org/ontology#requiresPrecaution', 'Keep away from open flames')
('http://msds.knowledge-graph.org/ontology#hasSupplier',      'Sigma-Aldrich')
```

> **Warning:** If `rows` is empty, first check the `GRAPH` clause. HANA SPARQL returns no results without the `GRAPH` wrapper, even if the triples exist. The second thing to check is the IRI prefix — the subject must match exactly what `insert_triples()` used when storing the graph.

Upload the remaining four PDFs (`MAT-002` through `MAT-005`) with the same pattern. After all five complete, you will have 250–350 rows in `MSDS_VECTORS` and 5 named graphs in the HANA RDF store.

---

## 5.9 Summary

This chapter built the pipeline that bridges PDF uploads and the dual-store knowledge layer. The architecture applies to any document type uploaded against an SAP Material Number. The key design decisions:

- **Parallel threads** — `ThreadPoolExecutor(max_workers=2)` runs the KG extraction (Gemini 2.5 Flash) and the vector embedding (`text-embedding-004`) simultaneously. These operations are independent: neither pipeline waits for the other. Wall-clock ingestion time equals the slower pipeline, not the sum.
- **Fire-and-forget with status polling** — the upload endpoint returns 202 in milliseconds. The CAP Fiori UI polls every 3 seconds. Decouples ingestion time from HTTP timeouts — essential for large documents on BTP CF.
- **Thread-local HANA connections** — `threading.local()` gives each worker thread its own connection object, eliminating race conditions without connection pooling infrastructure.
- **Different text strategies per pipeline** — the vector pipeline chunks to 500 tokens for embedding precision; the KG pipeline sends the full document for triple extraction quality.
- **Document-type agnostic vector pipeline** — the same chunker and embed logic handles any PDF. Only the KG extraction prompt changes per document type.
- **Error isolation** — exceptions in one pipeline are caught and persisted as `ERROR` status without interrupting the other pipeline.
- **MSDS_DOCUMENTS as control plane** — status, error messages, and counts are persisted in HANA. The CAP service reads this table directly. Operators can triage failures with SQL, not log files.

---

## 5.10 Checkpoint

Before moving to Chapter 6, confirm each of the following:

- [ ] `agents/srv/doc_srv.py` exists and `uvicorn main:app --port 8000` starts without import errors.
- [ ] `POST /process-upload` with a real PDF returns `{"status": "processing"}` within 500 ms.
- [ ] `GET /status/{materialNumber}` returns `"complete": true` within 30 seconds for a 20–40 page document.
- [ ] Five documents uploaded; all show `kgStatus = "DONE"` and `vectorStatus = "DONE"`.
- [ ] `SELECT COUNT(*) FROM MSDS_VECTORS WHERE MATERIAL_NUMBER = 'MAT-001'` returns a positive number.
- [ ] `SELECT CARDINALITY(EMBEDDING) FROM MSDS_VECTORS FETCH FIRST 1 ROWS ONLY` returns `768`.
- [ ] SPARQL query against `MSDS_Graph/BATCH-QC-MAT-001` returns at least one triple with predicate `certifiedBy`.
- [ ] Re-uploading the same PDF overwrites existing rows rather than creating duplicates.
- [ ] Uploading a scan-only PDF results in both statuses showing `ERROR`, not `PROCESSING`.

With the ingestion pipeline verified and five documents loaded into both stores, you are ready for the agentic layer. Chapter 6 introduces LangGraph — the framework that will orchestrate queries against these two stores in parallel and synthesise a single coherent answer.

---

*End of Chapter 5*
