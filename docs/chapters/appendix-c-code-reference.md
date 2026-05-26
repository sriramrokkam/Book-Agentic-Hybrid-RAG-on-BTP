# Appendix C — Full Code Reference

This appendix is a file-by-file reference for the complete repository. Each entry states what the file does, which chapter covers it in depth, and the key symbols it exports. Use this to locate any function or configuration value without re-reading the chapters.

---

## Repository Layout

```
book-agentic-hybrid-rag-on-btp/
├── agents/                    # Python FastAPI service
│   ├── main.py
│   ├── requirements.txt
│   ├── manifest.yml
│   ├── .env.example
│   ├── agents/                # LangGraph chains and graphs
│   │   ├── state.py
│   │   ├── vector_chain.py
│   │   ├── kg_chain.py
│   │   ├── orchestrator.py
│   │   └── supervisor.py
│   └── srv/                   # Service layer (HANA, Vertex AI)
│       ├── hdb_srv.py
│       ├── vector_srv.py
│       ├── kg_srv.py
│       ├── doc_srv.py
│       └── vertex_srv.py
├── cap-srv/                   # Node.js CAP OData service
│   ├── db/schema.cds
│   ├── srv/service.cds
│   ├── srv/service.js
│   ├── package.json
│   ├── mta.yaml
│   └── .env.example
├── MSDS_Ontology.ttl          # OWL ontology for the knowledge graph
└── README.md
```

---

## Python Agent Service (`agents/`)

### `agents/main.py`

**Chapters:** 6, 8, 9

FastAPI application entrypoint. Defines all HTTP routes, validates `material_number` against a strict regex, and delegates work to the service layer and LangGraph agents.

**Routes**

| Method | Path | Chapter | Description |
|--------|------|---------|-------------|
| `GET` | `/health` | — | Liveness probe; returns `{"status": "ok"}` |
| `POST` | `/query` | 8 | Parallel hybrid RAG — runs vector and KG chains simultaneously |
| `POST` | `/query-advanced` | 9 | Multi-agent supervisor query; pass `use_supervisor: true` for complex questions |
| `POST` | `/process-upload` | 6 | Accepts PDF multipart upload; returns immediately with `{"status": "processing"}` |
| `GET` | `/status/{material_number}` | 6 | Polls dual-pipeline ingestion status from `MSDS_DOCUMENTS` |
| `DELETE` | `/delete/{material_number}` | 6 | Cascade-deletes vectors, named graph, and `MSDS_DOCUMENTS` row |
| `POST` | `/admin/load-ontology` | 5 | Loads `MSDS_Ontology.ttl` into HANA named graph |

**Key constants**

| Name | Value | Purpose |
|------|-------|---------|
| `MATERIAL_RE` | `^[A-Za-z0-9_-]+$` | Guards all path parameters against SPARQL injection |

**Pydantic models**

| Model | Fields | Used by |
|-------|--------|---------|
| `QueryRequest` | `question`, `material_number`, `history` | `/query` |
| `QueryResponse` | `answer`, `kg_sparql`, `kg_facts`, `vector_chunks`, `sources` | `/query`, `/query-advanced` responses |
| `AdvancedQueryRequest` | `question`, `material_number`, `history`, `use_supervisor` | `/query-advanced` |

---

### `agents/requirements.txt`

**Chapter:** 3 (environment setup)

Pins all Python dependencies. Key packages:

| Package | Purpose |
|---------|---------|
| `fastapi`, `uvicorn` | HTTP server |
| `hdbcli` | SAP HANA Cloud driver |
| `google-cloud-aiplatform`, `vertexai` | Vertex AI SDK |
| `langgraph`, `langchain-google-genai`, `langchain-core` | LangGraph + Gemini integration |
| `PyMuPDF` | PDF text extraction |
| `python-dotenv` | `.env` file loading |

---

### `agents/manifest.yml`

**Chapter:** 11 (BTP deployment)

Cloud Foundry push descriptor for the Python service. Specifies the application name, memory allocation, Python buildpack, and environment variable bindings for the BTP CF environment.

---

### `agents/agents/state.py`

**Chapters:** 8, 9

Defines the two `TypedDict` state schemas used by LangGraph. Every node in the graphs reads from and writes to these types.

| Class | Chapter | Description |
|-------|---------|-------------|
| `HybridRAGState` | 8 | State for the parallel hybrid RAG orchestrator |
| `SupervisorState` | 9 | State for the multi-agent supervisor graph |

**`HybridRAGState` fields**

| Field | Type | Direction |
|-------|------|-----------|
| `question` | `str` | Input |
| `material_number` | `str` | Input |
| `history` | `List[dict]` | Input |
| `vector_answer` | `str` | Vector chain output |
| `vector_chunks` | `List[dict]` | Vector chain output |
| `kg_answer` | `str` | KG chain output |
| `kg_sparql` | `str` | KG chain output (generated SPARQL) |
| `kg_facts` | `List[dict]` | KG chain output |
| `final_answer` | `str` | Merged output |
| `sources` | `List[str]` | Merged output |
| `error` | `Optional[str]` | Control |

**`SupervisorState` fields** (additional fields beyond shared inputs/outputs)

| Field | Type | Set by |
|-------|------|--------|
| `sub_questions` | `Dict[str, str]` | `supervisor_node` |
| `specialists_needed` | `List[str]` | `supervisor_node` |
| `hazard_answer` | `str` | `hazard_agent` |
| `compliance_answer` | `str` | `compliance_agent` |
| `safety_answer` | `str` | `safety_agent` |

---

### `agents/agents/vector_chain.py`

**Chapter:** 8

Implements the vector retrieval chain. Steps: embed question with `text-embedding-004`, run cosine similarity SQL against `MSDS_VECTORS`, summarise the top-5 chunks with Gemini.

| Symbol | Description |
|--------|-------------|
| `run_vector_chain(state)` | Main entry point; accepts `HybridRAGState`, returns dict of state updates (`vector_answer`, `vector_chunks`) |
| `COSINE_SEARCH_SQL` | Module-level SQL constant; uses `COSINE_SIMILARITY(EMBEDDING, TO_REAL_VECTOR(?))` ordered by score descending |

---

### `agents/agents/kg_chain.py`

**Chapter:** 8

Implements the knowledge graph retrieval chain. Steps: generate SPARQL from question using Gemini, execute via `SPARQL_EXECUTE`, retry with a broader fallback query if empty, summarise facts with Gemini.

| Symbol | Description |
|--------|-------------|
| `run_kg_chain(state)` | Main entry point; accepts `HybridRAGState`, returns dict of state updates (`kg_answer`, `kg_sparql`, `kg_facts`) |
| `SPARQL_GEN_PROMPT` | Prompt template instructing Gemini to generate a `GRAPH`-scoped SPARQL SELECT |
| `SPARQL_FALLBACK_PROMPT` | Broader prompt used when first SPARQL returns no rows |
| `GRAPH_URI_PREFIX` | `"http://msds.knowledge-graph.org/MSDS_Graph/"` — prefixed with `material_number` to form named-graph IRI |
| `_execute_sparql(sparql)` | Internal helper; calls `SPARQL_EXECUTE` stored procedure and returns rows |

**Important:** every SPARQL triple pattern must be wrapped in `GRAPH <iri> { ... }` or HANA returns empty results silently.

---

### `agents/agents/orchestrator.py`

**Chapter:** 8

Runs `run_vector_chain` and `run_kg_chain` in parallel using `ThreadPoolExecutor(max_workers=2)`. Wall-clock latency equals the slower of the two chains, not their sum.

| Symbol | Description |
|--------|-------------|
| `run_hybrid_rag(state)` | Dispatches both chains, merges state updates, calls `merge_results`, returns complete state dict |
| `merge_results(kg_answer, vector_answer, question, material_number)` | Synthesises both answers; if both are present, calls Gemini; if only one, returns it directly |
| `CHAIN_TIMEOUT_SECONDS` | `30` — per-chain timeout before the future is abandoned |

---

### `agents/agents/supervisor.py`

**Chapter:** 9

Implements the multi-agent supervisor LangGraph. Three-node graph: `supervisor` decomposes the question into sub-questions, `specialists` runs domain agents in parallel, `summary` synthesises the final answer.

| Symbol | Description |
|--------|-------------|
| `build_supervisor_graph()` | Compiles and returns a `StateGraph(SupervisorState)` with nodes `supervisor → specialists → summary` |
| `supervisor_app` | Module-level pre-built instance; safe to import and call from `main.py` |
| `supervisor_node(state)` | Calls Gemini with `SUPERVISOR_PROMPT` to pick specialists and write sub-questions into state |
| `parallel_specialists_node(state)` | Runs only the specialists listed in `specialists_needed` via `ThreadPoolExecutor` |
| `hazard_agent(state)` | KG-focused; answers questions about GHS codes and hazard classifications |
| `compliance_agent(state)` | KG-focused; answers questions about exposure limits and regulatory thresholds |
| `safety_agent(state)` | Vector-focused; answers questions about precautions, PPE, first aid |
| `summary_agent(state)` | Synthesises answers from all invoked specialists into a single structured response |

---

## Service Layer (`agents/srv/`)

### `agents/srv/hdb_srv.py`

**Chapter:** 4

Thread-local SAP HANA Cloud connection manager. Each thread in the FastAPI process gets its own `hdbcli` connection. Connections are never shared across threads.

| Symbol | Description |
|--------|-------------|
| `get_connection()` | Returns (or creates) the HANA connection for the current thread |
| `close_thread_connection()` | Closes and clears the current thread's connection |
| `_local` | `threading.local()` storage for per-thread connections |

Connection parameters are read from environment variables `HANA_HOST`, `HANA_PORT`, `HANA_USER`, `HANA_PASSWORD`. TLS is always enabled (`encrypt=True`).

---

### `agents/srv/vector_srv.py`

**Chapter:** 4

CRUD operations against the `MSDS_VECTORS` HANA table. The table is created lazily on first insert; the embedding dimension is inferred from the first embedding response.

| Symbol | Description |
|--------|-------------|
| `store_embedding(material_number, chunk_text, chunk_index, embedding)` | Inserts one chunk and its embedding vector |
| `upsert_vectors(conn, material_number, chunk_index, chunk_text, embedding)` | UPSERT by composite key; used by `doc_srv` during re-ingestion |
| `search_similar(question, material_number, top_k=5)` | Embeds question, runs `COSINE_SIMILARITY` SQL, returns list of `{chunk, chunk_index, score}` |
| `delete_vectors(material_number)` | Deletes all vectors for a material; returns row count |
| `count_vectors(material_number)` | Returns number of stored vectors for a material |
| `TABLE_NAME` | `"MSDS_VECTORS"` |

---

### `agents/srv/kg_srv.py`

**Chapter:** 5

SPARQL operations against HANA Cloud named graphs. Validates `material_number` before every SPARQL construction to prevent injection.

| Symbol | Description |
|--------|-------------|
| `store_triples(material_number, triples)` | Inserts a list of `{subject, predicate, object}` dicts as a named RDF graph; returns triples stored |
| `insert_triples(conn, material_number, triples)` | Explicit-connection variant of `store_triples`; used by `doc_srv` for thread-local callers |
| `query_graph(material_number, question)` | Generates SPARQL with Gemini, executes it, returns `{facts, sparql, count}` |
| `delete_graph(material_number)` | Drops the named graph; returns `True` on success |
| `count_triples(material_number)` | Returns triple count for a material's named graph |
| `load_ontology(ttl_path)` | Loads a `.ttl` file into the ontology named graph; drops existing graph first |
| `extract_triples(text, material_number)` | Calls Gemini to extract structured triples from free text; returns list of dicts |
| `GRAPH_BASE` | `"http://msds.knowledge-graph.org/MSDS_Graph"` |
| `ONTOLOGY_GRAPH_IRI` | `"http://msds.knowledge-graph.org/ontology"` |
| `MATERIAL_RE` | `^[A-Za-z0-9_-]+$` |

Named-graph IRI pattern: `{GRAPH_BASE}/{material_number}`

---

### `agents/srv/doc_srv.py`

**Chapter:** 6

Orchestrates the dual-pipeline PDF ingestion. Runs the vector pipeline and the KG pipeline in separate background threads. Status is persisted to `MSDS_DOCUMENTS` so polling survives process restarts.

| Symbol | Description |
|--------|-------------|
| `_run_dual_pipeline(tmp_path, material_number, material_name)` | Entry point for background execution; extracts PDF text, runs both pipelines in parallel, updates status |
| `_vector_pipeline(text, material_number, material_name)` | Chunks text, embeds each chunk, upserts into `MSDS_VECTORS` |
| `_kg_pipeline(text, material_number)` | Extracts triples with Gemini, stores them as a named graph |
| `_save_upload_sync(upload)` | Writes `UploadFile` to a temp file; returns path |
| `_mark_processing(material_number)` | UPSERTs `MSDS_DOCUMENTS` row with status `PROCESSING` before returning HTTP response |
| `chunk_text(text, material_name, chunk_tokens=500, overlap_tokens=50)` | Generator; yields overlapping chunks split on sentence boundaries |
| `extract_pdf_text(path)` | Opens PDF with PyMuPDF; returns `(full_text, page_count)`; raises `ValueError` for image-only PDFs |
| `get_hana_connection()` | Thread-local HANA connection (mirrors `hdb_srv.get_connection`) |
| `close_thread_connection()` | Releases thread-local connection |

---

### `agents/srv/vertex_srv.py`

**Chapters:** 4, 5

Vertex AI / Gemini client. Uses double-checked locking to initialise the SDK exactly once per process. All public functions are safe to call from multiple threads.

| Symbol | Description |
|--------|-------------|
| `get_llm()` | Returns a `GenerativeModel("gemini-2.5-flash-preview-05-20")` instance |
| `get_embedding_model()` | Returns a `TextEmbeddingModel` for `text-embedding-004` |
| `embed_text(text)` | Embeds a single string; returns a list of 768 `float` values |
| `generate_text(prompt)` | Calls Gemini with a plain-text prompt; returns response string |
| `_ensure_initialized()` | Internal; calls `vertexai.init(project, location)` behind a lock |

Model identifiers: LLM = `gemini-2.5-flash-preview-05-20`, embedding = `text-embedding-004`.

---

## CAP OData Service (`cap-srv/`)

### `cap-srv/db/schema.cds`

**Chapter:** 10

CDS data model. Namespace `msds`.

| Entity | Key | Description |
|--------|-----|-------------|
| `Documents` | `materialNumber` | Tracks each ingested MSDS document with dual-pipeline status columns |
| `QueryLog` | `ID` (UUID) | Optional audit trail for every query submitted via the UI |

**`Documents` columns**

| Column | Type | Notes |
|--------|------|-------|
| `materialNumber` | `String(100)` | Primary key; matches Python `material_number` |
| `materialName` | `String(500)` | Human-readable name |
| `status` | `String(20)` | KG pipeline: `PENDING`, `PROCESSING`, `DONE`, `ERROR` |
| `kgError` | `String(1000)` | KG error message if status = ERROR |
| `vectorStatus` | `String(20)` | Vector pipeline: same set of values |
| `vectorError` | `String(1000)` | Vector error message |
| `createdAt`, `updatedAt` | `Timestamp` | Lifecycle timestamps |

---

### `cap-srv/srv/service.cds`

**Chapter:** 10

OData V4 service definition. Service name `MSDSService`, path `/api`.

| Artifact | Type | Description |
|----------|------|-------------|
| `Documents` | Entity projection | Wraps `msds.Documents` with bound actions |
| `QueryLog` | Read-only projection | Wraps `msds.QueryLog` |
| `ingestDocument(materialName, fileContent, fileName)` | Bound action on `Documents` | Proxies to Python `/process-upload` |
| `deleteDocument()` | Bound action on `Documents` | Proxies to Python `DELETE /delete/{id}` |
| `query(question, materialNumber, history)` | Unbound action | Proxies to Python `POST /query` |
| `queryAdvanced(question, materialNumber, history, useSupervisor)` | Unbound action | Proxies to Python `POST /query-advanced` |
| `ingestionStatus(materialNumber)` | Unbound function | Proxies to Python `GET /status/{id}` |

---

### `cap-srv/srv/service.js`

**Chapter:** 10

CAP service handler. Implements all action handlers by forwarding requests to the Python FastAPI service. `AGENT_URL` is the single configuration point for the backend URL.

| Symbol | Description |
|--------|-------------|
| `agentPost(path, body)` | Internal helper; POST JSON to `AGENT_URL + path`, 60 s timeout |
| `agentDelete(path)` | Internal helper; DELETE to `AGENT_URL + path`, 30 s timeout |
| `srv.on("query", ...)` | Handles `query` action; serialises history to JSON before forwarding |
| `srv.on("queryAdvanced", ...)` | Handles `queryAdvanced`; passes `use_supervisor` flag |
| `srv.on("ingestionStatus", ...)` | Handles `ingestionStatus` function |
| `srv.on("ingestDocument", "Documents", ...)` | Builds multipart form data and POSTs to `/process-upload` |
| `srv.on("deleteDocument", "Documents", ...)` | Calls `agentDelete` with the material number from URL params |
| `AGENT_URL` | `process.env.AGENT_URL \|\| "http://localhost:8000"` |

---

## Ontology (`MSDS_Ontology.ttl`)

**Chapter:** 5

OWL ontology in Turtle format. Namespace prefix: `msds: <http://msds.knowledge-graph.org/ontology#>`. Load via `POST /admin/load-ontology` after provisioning a fresh HANA instance.

**Classes**

| IRI | Label | Description |
|-----|-------|-------------|
| `msds:Material` | Material | The MSDS document subject |
| `msds:HazardCode` | GHS Hazard Code | GHS classification codes (e.g. H225, H319) |
| `msds:ExposureLimit` | Occupational Exposure Limit | TWA / STEL values |
| `msds:Precaution` | Safety Precaution | Handling, storage, PPE instructions |
| `msds:Supplier` | Supplier | Manufacturer or distributor |

**Object properties** (node to node)

| Property | Domain | Range |
|----------|--------|-------|
| `msds:hasHazardCode` | `Material` | `HazardCode` |
| `msds:hasExposureLimit` | `Material` | `ExposureLimit` |
| `msds:requiresPrecaution` | `Material` | `Precaution` |
| `msds:hasSupplier` | `Material` | `Supplier` |

**Datatype properties** (node to literal)

| Property | Domain | Description |
|----------|--------|-------------|
| `msds:code` | `HazardCode` | Hazard code string value |
| `msds:description` | Any | Free-text description |
| `msds:limitValue` | `ExposureLimit` | Numeric limit |
| `msds:limitUnit` | `ExposureLimit` | Unit (ppm, mg/m³, etc.) |
| `msds:precautionText` | `Precaution` | Precaution instruction text |

---

## Environment Variables Reference

### Python agent service (`agents/.env.example`)

| Variable | Description | Where to find |
|----------|-------------|---------------|
| `HANA_HOST` | HANA Cloud instance hostname | SAP BTP cockpit → HANA Cloud → Copy SQL Endpoint (hostname only) |
| `HANA_PORT` | HANA SQL/MDC port (default `443`) | Same SQL endpoint — port after the colon |
| `HANA_USER` | HANA database user | Created in HANA Database Explorer or via SQL |
| `HANA_PASSWORD` | HANA user password | Set when creating the user |
| `GCP_PROJECT_ID` | Google Cloud project ID | GCP console → project selector |
| `GCP_LOCATION` | Vertex AI region (default `us-central1`) | Must match the region where Vertex AI APIs are enabled |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to GCP service account JSON key | GCP console → IAM → Service Accounts → Keys |
| `LANGCHAIN_TRACING_V2` | Enable LangSmith tracing (`true`/`false`) | LangSmith account settings |
| `LANGCHAIN_ENDPOINT` | LangSmith API endpoint | `https://api.smith.langchain.com` (fixed) |
| `LANGCHAIN_API_KEY` | LangSmith API key | LangSmith → Settings → API Keys |

### CAP service (`cap-srv/.env.example`)

| Variable | Description | Where to find |
|----------|-------------|---------------|
| `AGENT_URL` | Base URL of the running Python FastAPI service | Local: `http://localhost:8000`; CF: output of `cf app hybrid-rag-agent` |

---

## Material Number Format Constraint

All endpoints and service functions enforce the pattern `^[A-Za-z0-9_-]+$` on the `material_number` parameter.

**Reason:** material numbers are interpolated directly into SPARQL named-graph IRIs and SPARQL query strings. Without this constraint, a crafted material number such as `ACET> . MALICIOUS_TRIPLE . <X` would break out of the IRI and inject arbitrary SPARQL — the triple-store equivalent of SQL injection. The regex allows only alphanumeric characters, hyphens, and underscores, none of which are SPARQL metacharacters.

The constraint is applied in three independent places:

1. `main.py` — `MATERIAL_RE` compiled regex validates all path parameters and request body fields via Pydantic validators before any function is called.
2. `kg_srv.py` — `_validate_material()` called at the top of every public function.
3. `service.js` — the CAP handler passes the material number through to the Python service unchanged; validation occurs server-side.

---

## Quick curl Reference

Replace `localhost:8000` with the deployed CF application URL for production calls.

**Liveness check**
```bash
curl http://localhost:8000/health
```

**Parallel hybrid RAG query**
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What are the GHS hazard codes?",
    "material_number": "ACETONE-001",
    "history": []
  }'
```

**Multi-agent supervisor query**
```bash
curl -X POST http://localhost:8000/query-advanced \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What hazard codes apply and what PPE is required?",
    "material_number": "ACETONE-001",
    "use_supervisor": true,
    "history": []
  }'
```

**Upload PDF for ingestion**
```bash
curl -X POST http://localhost:8000/process-upload \
  -F "file=@/path/to/ACETONE-001.pdf" \
  -F "materialNumber=ACETONE-001" \
  -F "materialName=Acetone"
```

**Poll ingestion status**
```bash
curl http://localhost:8000/status/ACETONE-001
```

**Delete document (cascade)**
```bash
curl -X DELETE http://localhost:8000/delete/ACETONE-001
```

**Load ontology (run once after provisioning)**
```bash
curl -X POST http://localhost:8000/admin/load-ontology
```

---

## Cross-Reference: Chapter to File

| Chapter | Primary files |
|---------|--------------|
| 3 — Platform Setup | `requirements.txt`, `cap-srv/package.json`, `README.md` |
| 4 — Vector Search on HANA Cloud | `srv/hdb_srv.py`, `srv/vector_srv.py`, `srv/vertex_srv.py` |
| 5 — Knowledge Graphs on HANA Cloud | `srv/kg_srv.py`, `srv/vertex_srv.py`, `MSDS_Ontology.ttl` |
| 6 — PDF Ingestion Pipeline | `srv/doc_srv.py`, `main.py` (upload/status/delete endpoints) |
| 7 — LangGraph Fundamentals | `agents/state.py` (TypedDict patterns) |
| 8 — Parallel Hybrid RAG Agent | `agents/state.py`, `agents/vector_chain.py`, `agents/kg_chain.py`, `agents/orchestrator.py`, `main.py` (`/query`) |
| 9 — Multi-Agent Supervisor | `agents/supervisor.py`, `agents/state.py` (`SupervisorState`), `main.py` (`/query-advanced`) |
| 10 — CAP and Fiori UI | `cap-srv/db/schema.cds`, `cap-srv/srv/service.cds`, `cap-srv/srv/service.js` |
| 11 — BTP Deployment | `manifest.yml`, `cap-srv/mta.yaml` |
