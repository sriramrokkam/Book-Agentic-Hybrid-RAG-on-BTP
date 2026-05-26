# Code Map — Chapter ↔ Source File Cross-Reference

Every source file in this repo corresponds to one or more book chapters.
Use this map to navigate between the book explanation and the working code.

---

## Part I — Foundations (Chapters 1–3)

Chapters 1–3 are conceptual and setup-focused. No source files are produced,
but they prepare the environment that all later code requires.

| Chapter | Topic | What you set up |
|---|---|---|
| Ch 1 | Welcome to the Agentic Era | Mental model only |
| Ch 2 | Why SAP Developers Should Care | Mental model only |
| Ch 3 | Platform Setup | BTP trial + HANA Cloud + Vertex AI credentials |

After Chapter 3 your `.env` file (from `agents/.env.example`) should be filled in.

---

## Part II — The Knowledge Layer (Chapters 4–6)

### Chapter 4: Vector Search on SAP HANA Cloud
> `docs/chapters/chapter-04-vector-search-hana.md`

| Concept | Source file | Key function |
|---|---|---|
| HANA connection (thread-local) | `agents/srv/hdb_srv.py` | `get_connection()` |
| Vertex AI embeddings | `agents/srv/vertex_srv.py` | `embed_text()` |
| Lazy table creation | `agents/srv/vector_srv.py` | `_ensure_table()` |
| Store a chunk embedding | `agents/srv/vector_srv.py` | `store_embedding()` |
| Cosine similarity search | `agents/srv/vector_srv.py` | `search_similar()` |
| Delete vectors for a material | `agents/srv/vector_srv.py` | `delete_vectors()` |
| Integration test | `agents/tests/test_vector.py` | `run_vector_test()` |

---

### Chapter 5: Knowledge Graphs on SAP HANA Cloud
> `docs/chapters/chapter-05-knowledge-graph-hana.md`

| Concept | Source file | Key function |
|---|---|---|
| OWL ontology | `MSDS_Ontology.ttl` | (declarative) |
| Load ontology into HANA | `agents/srv/kg_srv.py` | `load_ontology()` |
| Triple extraction (Gemini) | `agents/srv/kg_srv.py` | `extract_triples()` |
| Store triples (named graph) | `agents/srv/kg_srv.py` | `store_triples()` |
| SPARQL query + summarise | `agents/srv/kg_srv.py` | `query_graph()` |
| Delete named graph | `agents/srv/kg_srv.py` | `delete_graph()` |
| Integration test | `agents/tests/test_kg.py` | `run_kg_test()` |

---

### Chapter 6: The PDF Ingestion Pipeline
> `docs/chapters/chapter-06-pdf-ingestion.md`

| Concept | Source file | Key function |
|---|---|---|
| PDF text extraction | `agents/srv/doc_srv.py` | `extract_pdf_text()` |
| Chunk text for vectors | `agents/srv/doc_srv.py` | `chunk_text()` |
| Dual-pipeline (parallel) | `agents/srv/doc_srv.py` | `_run_dual_pipeline()` |
| Vector pipeline thread | `agents/srv/doc_srv.py` | `_vector_pipeline()` |
| KG pipeline thread | `agents/srv/doc_srv.py` | `_kg_pipeline()` |
| Upload endpoint | `agents/main.py` | `POST /process-upload` |
| Status polling endpoint | `agents/main.py` | `GET /status/{id}` |
| Cascade delete endpoint | `agents/main.py` | `DELETE /delete/{id}` |
| Load ontology endpoint | `agents/main.py` | `POST /admin/load-ontology` |

---

## Part III — Agentic Orchestration (Chapters 7–9)

### Chapter 7: LangGraph Fundamentals
> `docs/chapters/chapter-07-langgraph-fundamentals.md`

| Concept | Source file | Key function |
|---|---|---|
| AgentState (TypedDict) | `agents/agents/simple_qa_agent.py` | `AgentState` |
| Graph nodes | `agents/agents/simple_qa_agent.py` | `retrieve_node`, `answer_node` |
| Conditional routing | `agents/agents/simple_qa_agent.py` | `route_after_check()` |
| Build + compile graph | `agents/agents/simple_qa_agent.py` | `build_graph()` |
| LangGraph tool definitions | `agents/tools/tools.py` | `ALL_TOOLS` list |

---

### Chapter 8: The Parallel Hybrid RAG Agent
> `docs/chapters/chapter-08-hybrid-rag-agent.md`

| Concept | Source file | Key function |
|---|---|---|
| Shared state definition | `agents/agents/state.py` | `HybridRAGState` |
| Vector chain | `agents/agents/vector_chain.py` | `run_vector_chain()` |
| KG chain (SPARQL gen + retry) | `agents/agents/kg_chain.py` | `run_kg_chain()` |
| Parallel dispatch (ThreadPoolExecutor) | `agents/agents/orchestrator.py` | `run_hybrid_rag()` |
| Merge logic | `agents/agents/orchestrator.py` | `merge_results()` |
| Query endpoint | `agents/main.py` | `POST /query` |

---

### Chapter 9: The Multi-Agent Supervisor Pattern
> `docs/chapters/chapter-09-multi-agent-supervisor.md`

| Concept | Source file | Key function |
|---|---|---|
| Supervisor state | `agents/agents/state.py` | `SupervisorState` |
| Routing node | `agents/agents/supervisor.py` | `supervisor_node()` |
| Hazard specialist | `agents/agents/supervisor.py` | `hazard_agent()` |
| Compliance specialist | `agents/agents/supervisor.py` | `compliance_agent()` |
| Safety specialist | `agents/agents/supervisor.py` | `safety_agent()` |
| Synthesis node | `agents/agents/supervisor.py` | `summary_agent()` |
| Build supervisor graph | `agents/agents/supervisor.py` | `build_supervisor_graph()` |
| Advanced query endpoint | `agents/main.py` | `POST /query-advanced` |

---

## Part IV — SAP Integration Layer (Chapters 10–11)

### Chapter 10: CAP Node.js OData V4
> *(chapter pending)*

| Concept | Source file | Key element |
|---|---|---|
| Data model | `cap-srv/db/schema.cds` | `entity Documents` |
| OData service definition | `cap-srv/srv/service.cds` | `service MSDSService` |
| Action handlers | `cap-srv/srv/service.js` | `srv.on(...)` |
| Upload → Python proxy | `cap-srv/srv/service.js` | `ingestDocument` handler |
| Delete → Python proxy | `cap-srv/srv/service.js` | `deleteDocument` handler |
| Query → Python proxy | `cap-srv/srv/service.js` | `query` handler |

---

### Chapter 11: Deploying to SAP BTP Cloud Foundry
> *(chapter pending)*

| Concept | Source file |
|---|---|
| Python CF manifest | `agents/manifest.yml` |
| MTA deployment descriptor | `cap-srv/mta.yaml` |
| Environment variables | `agents/.env.example`, `cap-srv/.env.example` |

---

## Appendices

| Appendix | Topic | Related files |
|---|---|---|
| Appendix A | BTP Trial Setup | `docs/screenshots/btp/` |
| Appendix B | GCP + Vertex AI Setup | `docs/screenshots/gcp/` |
| Appendix C | Full Code Reference | All files in `agents/` and `cap-srv/` |
| Appendix D | Joule A2A *(enterprise)* | `joule/README.md` |
| Appendix E | SAP AI Core swap-in *(enterprise)* | Swap `agents/srv/vertex_srv.py` |

---

## Reading Flow

```
Chapter 3  →  fill in agents/.env
Chapter 4  →  agents/srv/hdb_srv.py + vertex_srv.py + vector_srv.py
Chapter 5  →  MSDS_Ontology.ttl + agents/srv/kg_srv.py
Chapter 6  →  agents/srv/doc_srv.py + main.py (upload/status/delete)
Chapter 7  →  agents/agents/simple_qa_agent.py + tools/tools.py
Chapter 8  →  agents/agents/state.py + vector_chain.py + kg_chain.py + orchestrator.py
Chapter 9  →  agents/agents/supervisor.py + main.py (query-advanced)
Chapter 10 →  cap-srv/db/ + cap-srv/srv/
Chapter 11 →  agents/manifest.yml + cap-srv/mta.yaml
```
