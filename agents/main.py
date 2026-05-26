"""
agents/main.py

FastAPI entrypoint for the Hybrid RAG Agent service.

Endpoints:
  GET  /health
  POST /query           — direct parallel hybrid RAG (Chapter 8)
  POST /query-advanced  — multi-agent supervisor (Chapter 9, optional)
  POST /process-upload  — PDF ingestion (fire-and-forget)
  GET  /status/{material_number} — ingestion status polling

Usage (local):
  uvicorn main:app --reload --port 8000

Usage (BTP CF):
  cf push  (uses manifest.yml)
"""
import re
import asyncio
import logging
from typing import List, Optional

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, validator

from agents.orchestrator import run_hybrid_rag
from agents.state import HybridRAGState
from agents.supervisor import supervisor_app
from agents.state import SupervisorState
from srv.doc_srv import (
    _save_upload_sync,
    _mark_processing,
    _run_dual_pipeline,
    get_hana_connection,
    close_thread_connection,
)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Hybrid RAG Agent — MSDS on SAP BTP",
    description=(
        "Parallel vector + knowledge-graph retrieval for Material Safety Data Sheets. "
        "Powered by SAP HANA Cloud, Google Vertex AI, and LangGraph."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten for production
    allow_methods=["*"],
    allow_headers=["*"],
)

MATERIAL_RE = re.compile(r"^[A-Za-z0-9_-]+$")


# ── Models ────────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str
    material_number: str
    history: List[dict] = []

    @validator("material_number")
    def validate_material(cls, v):
        if not MATERIAL_RE.match(v):
            raise ValueError("material_number contains invalid characters")
        return v

    @validator("question")
    def validate_question(cls, v):
        if not v.strip():
            raise ValueError("question must not be empty")
        return v.strip()


class QueryResponse(BaseModel):
    answer: str
    kg_sparql: Optional[str] = None
    kg_facts: Optional[List] = None
    vector_chunks: Optional[List] = None
    sources: Optional[List[str]] = None


class AdvancedQueryRequest(BaseModel):
    question: str
    material_number: str
    history: List[dict] = []
    use_supervisor: bool = False

    @validator("material_number")
    def validate_material(cls, v):
        if not re.match(r"^[A-Za-z0-9_-]+$", v):
            raise ValueError("material_number contains invalid characters")
        return v


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ── Direct hybrid RAG query ───────────────────────────────────────────────────

@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest):
    """
    Run both vector and KG chains in parallel and return a synthesised answer.
    """
    state: HybridRAGState = {
        "question": request.question,
        "material_number": request.material_number,
        "history": request.history,
        "vector_answer": "",
        "vector_chunks": [],
        "kg_answer": "",
        "kg_sparql": "",
        "kg_facts": [],
        "final_answer": "",
        "sources": [],
        "error": None,
    }

    result = run_hybrid_rag(state)

    if not result.get("final_answer"):
        raise HTTPException(status_code=500, detail="Agent returned no answer")

    return QueryResponse(
        answer=result["final_answer"],
        kg_sparql=result.get("kg_sparql"),
        kg_facts=result.get("kg_facts"),
        vector_chunks=result.get("vector_chunks"),
        sources=result.get("sources"),
    )


# ── Advanced query (supervisor) ───────────────────────────────────────────────

@app.post("/query-advanced", response_model=QueryResponse)
def query_advanced(request: AdvancedQueryRequest):
    """
    Optionally route through the multi-agent supervisor for multi-domain questions.
    Pass use_supervisor=true for complex questions spanning hazard + compliance + safety.
    """
    if not request.use_supervisor:
        # Fall back to direct hybrid RAG
        return query(
            QueryRequest(
                question=request.question,
                material_number=request.material_number,
                history=request.history,
            )
        )

    state: SupervisorState = {
        "question": request.question,
        "material_number": request.material_number,
        "history": request.history,
        "sub_questions": {},
        "specialists_needed": [],
        "hazard_answer": "",
        "compliance_answer": "",
        "safety_answer": "",
        "final_answer": "",
        "sources": [],
        "error": None,
    }

    result = supervisor_app.invoke(state)

    return QueryResponse(
        answer=result.get("final_answer", ""),
        sources=result.get("sources"),
    )


# ── PDF upload ────────────────────────────────────────────────────────────────

@app.post("/process-upload")
async def process_upload(
    file: UploadFile = File(...),
    materialNumber: str = Form(...),
    materialName: str = Form(...),
):
    """
    Accept a PDF upload and trigger dual-pipeline ingestion (fire-and-forget).
    Returns immediately with {"status": "processing"}.
    Poll GET /status/{materialNumber} for completion.
    """
    if not MATERIAL_RE.match(materialNumber):
        return JSONResponse(
            status_code=400,
            content={
                "error": "Invalid materialNumber. "
                         "Use only letters, digits, hyphens, underscores."
            },
        )

    loop = asyncio.get_event_loop()

    # Write upload to a temp file synchronously (UploadFile is not async-safe with shutil)
    tmp_path = await loop.run_in_executor(None, _save_upload_sync, file)

    # Persist PROCESSING status before returning
    _mark_processing(materialNumber)

    # Fire and forget — background threads run after HTTP response is sent
    loop.run_in_executor(
        None, _run_dual_pipeline, tmp_path, materialNumber, materialName
    )

    return {"status": "processing", "materialNumber": materialNumber}


# ── Ingestion status ──────────────────────────────────────────────────────────

@app.get("/status/{material_number}")
def get_status(material_number: str):
    """
    Return ingestion status for a material.
    complete=true when both pipelines have reached DONE or ERROR.
    """
    if not MATERIAL_RE.match(material_number):
        return JSONResponse(status_code=400, content={"error": "Invalid materialNumber"})

    conn = get_hana_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT STATUS, VECTOR_STATUS, KG_ERROR, VECTOR_ERROR, UPDATED_AT
        FROM   MSDS_DOCUMENTS
        WHERE  MATERIAL_NUMBER = ?
        """,
        (material_number,),
    )
    row = cursor.fetchone()
    cursor.close()
    close_thread_connection()

    if not row:
        return JSONResponse(status_code=404, content={"error": "Material not found"})

    kg_status, vector_status, kg_error, vector_error, updated_at = row
    return {
        "materialNumber": material_number,
        "kgStatus": kg_status,
        "vectorStatus": vector_status,
        "kgError": kg_error,
        "vectorError": vector_error,
        "updatedAt": str(updated_at),
        "complete": (
            kg_status in ("DONE", "ERROR") and vector_status in ("DONE", "ERROR")
        ),
    }
