"""
agents/srv/doc_srv.py

PDF ingestion service — dual-pipeline (vector + KG) running in parallel threads.

Endpoints exposed by main.py:
  POST /process-upload   — fire-and-forget ingestion
  GET  /status/{material_number}

Design decisions:
  - Thread-local HANA connections (hdbcli is not thread-safe)
  - Fire-and-forget: HTTP response returned before pipelines finish
  - Status persisted to MSDS_DOCUMENTS in HANA so it survives restarts
  - Error isolation: failure in one pipeline does not cancel the other
"""
import os
import re
import tempfile
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import fitz  # PyMuPDF
from hdbcli import dbapi
from dotenv import load_dotenv

from .vertex_srv import embed_text
from .vector_srv import upsert_vectors
from .kg_srv import extract_triples_from_text, insert_triples

load_dotenv()

# ── Thread-local HANA connection ──────────────────────────────────────────────

_thread_local = threading.local()


def get_hana_connection() -> dbapi.Connection:
    """
    Returns a HANA connection for the current thread.
    Creates one on first access; reuses it within the same thread.
    """
    if not hasattr(_thread_local, "conn") or _thread_local.conn is None:
        _thread_local.conn = dbapi.connect(
            address=os.environ["HANA_HOST"],
            port=int(os.environ.get("HANA_PORT", 443)),
            user=os.environ["HANA_USER"],
            password=os.environ["HANA_PASSWORD"],
            encrypt=True,
            sslValidateCertificate=False,
        )
    return _thread_local.conn


def close_thread_connection() -> None:
    """Close and clear the HANA connection for the current thread."""
    if hasattr(_thread_local, "conn") and _thread_local.conn is not None:
        try:
            _thread_local.conn.close()
        except Exception:
            pass
        _thread_local.conn = None


# ── PDF text extraction ───────────────────────────────────────────────────────

def extract_pdf_text(path: str) -> tuple[str, int]:
    """
    Extract text from a PDF file.
    Returns (full_text, page_count).
    Raises ValueError if the PDF has no extractable text layer.
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


def _save_upload_sync(upload) -> str:
    """Save an UploadFile to a temp file. Returns path. Caller must delete."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        shutil.copyfileobj(upload.file, tmp)
        return tmp.name


# ── Chunker ───────────────────────────────────────────────────────────────────

def chunk_text(
    text: str,
    material_name: str,
    chunk_tokens: int = 500,
    overlap_tokens: int = 50,
):
    """
    Yield overlapping chunks of approximately chunk_tokens each,
    split on sentence boundaries. Prefixes each chunk with material_name.
    Token estimation: 1 token ≈ 0.75 words (English prose).
    """
    import re as _re
    chunk_words = int(chunk_tokens * 0.75)
    overlap_words = int(overlap_tokens * 0.75)

    sentences = _re.split(r"(?<=[.!?])\s+", text.strip())

    current_chunk: list[str] = []
    current_count: int = 0
    prefix = f"Material: {material_name}\n\n"

    for sentence in sentences:
        word_count = len(sentence.split())
        if current_count + word_count > chunk_words and current_chunk:
            yield prefix + " ".join(current_chunk)
            overlap_start = max(0, len(current_chunk) - overlap_words)
            current_chunk = current_chunk[overlap_start:]
            current_count = sum(len(s.split()) for s in current_chunk)
        current_chunk.append(sentence)
        current_count += word_count

    if current_chunk:
        yield prefix + " ".join(current_chunk)


# ── Status helpers ────────────────────────────────────────────────────────────

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


def _mark_vector_status(
    material_number: str, status: str, error_message: Optional[str] = None
) -> None:
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


def _mark_kg_status(
    material_number: str, status: str, error_message: Optional[str] = None
) -> None:
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


# ── Pipeline threads ──────────────────────────────────────────────────────────

def _vector_pipeline(text: str, material_number: str, material_name: str) -> None:
    """Thread 1: chunk text, embed each chunk, upsert into MSDS_VECTORS."""
    conn = get_hana_connection()
    chunks = list(chunk_text(text, material_name))

    for i, chunk in enumerate(chunks):
        embedding = embed_text(chunk)
        upsert_vectors(
            conn=conn,
            material_number=material_number,
            chunk_index=i,
            chunk_text=chunk,
            embedding=embedding,
        )

    close_thread_connection()


def _kg_pipeline(text: str, material_number: str) -> None:
    """Thread 2: extract triples from full text with Gemini, store as named graph."""
    conn = get_hana_connection()
    triples = extract_triples_from_text(text, material_number)

    if not triples:
        raise ValueError(
            f"Zero triples extracted for '{material_number}'. "
            "Check document quality and ontology alignment."
        )

    insert_triples(conn=conn, material_number=material_number, triples=triples)
    close_thread_connection()


def _run_dual_pipeline(
    tmp_path: str,
    material_number: str,
    material_name: str,
) -> None:
    """
    Orchestrates both pipelines in parallel via ThreadPoolExecutor.
    Called in a background thread — must not raise unhandled exceptions.
    """
    try:
        text, _page_count = extract_pdf_text(tmp_path)
    except ValueError as exc:
        _mark_vector_status(material_number, "ERROR", str(exc))
        _mark_kg_status(material_number, "ERROR", str(exc))
        os.unlink(tmp_path)
        return

    vector_error = None
    kg_error = None

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_vector = executor.submit(_vector_pipeline, text, material_number, material_name)
        future_kg = executor.submit(_kg_pipeline, text, material_number)

        for future in as_completed([future_vector, future_kg]):
            try:
                future.result()
            except Exception as exc:
                if future is future_vector:
                    vector_error = str(exc)
                else:
                    kg_error = str(exc)

    _mark_vector_status(material_number, "ERROR" if vector_error else "DONE", vector_error)
    _mark_kg_status(material_number, "ERROR" if kg_error else "DONE", kg_error)

    try:
        os.unlink(tmp_path)
    except OSError:
        pass
