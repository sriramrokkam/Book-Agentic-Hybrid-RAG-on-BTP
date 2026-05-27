# Chapter 1: The SAP Document Problem — And Why BTP Is the Right Place to Solve It

## 1.1 The Document Fragmentation Problem in SAP Landscapes

Every material in an SAP ERP or S/4HANA system has a Material Number — the unique identifier you work with in MM03, MM60, QM, and across the supply chain. Over a material's lifecycle, a set of documents accumulates around it: Material Safety Data Sheets (MSDS/SDS), Batch Quality Certificates, Goods Receiving Inspection Reports, Supplier Invoices, Equipment Maintenance History, User and Installation Manuals, Legal Compliance Documents, and Regulatory Filings. These documents collectively define what the material is, how it behaves, how it must be handled, and what legal obligations govern its use.

Here is the problem: standard SAP provides no single transaction where all of these documents are stored, linked to the material, and made intelligently searchable. In practice they end up scattered. MSDS sheets live in a SharePoint folder someone set up in 2014. Batch certificates are emailed by suppliers and archived in Outlook. Inspection reports sit in a plant-level file server. DMS contains some documents but has no query interface beyond document type and metadata fields.

When a quality engineer asks *"Was this batch of material 800021 certified before it shipped?"* she emails a colleague and waits. When a safety officer asks *"What are the storage temperature limits for this chemical?"* he opens a PDF manually and reads through Section 7. When a procurement analyst needs to confirm a supplier invoice against a goods receipt, he has two systems open side by side.

This fragmentation is structural. SAP's document management capabilities — GOS attachments, DMS with DIR objects, extended object links — handle document storage and classification. What they do not provide is intelligent retrieval. You cannot open any standard SAP transaction, type a natural-language question about a material, and get a direct answer synthesised from the documents attached to it. You retrieve the document and do the reading yourself.

This is the gap this book fills: an **Agentic Hybrid RAG Document Intelligence Platform on SAP BTP** that:

- Accepts any PDF document linked to an SAP Material Number, validated against your live S/4HANA product catalogue via `API_PRODUCT_SRV` OData
- Ingests each document into a HANA Cloud vector table (`MSDS_VECTORS`, `REAL_VECTOR` column type) and into a named RDF graph (`MSDS_Graph/MAT-{material}`) simultaneously, in one upload
- Answers natural-language questions by running vector retrieval and SPARQL graph retrieval in parallel (`ThreadPoolExecutor`), merging the results, and synthesising a single cited answer via Gemini 2.5 Flash
- Exposes the full capability as a CAP Node.js OData V4 service with a Fiori Elements UI — the SAP-native interface your users already know
- Runs free: SAP BTP trial + Google Cloud $300 free credit

The **MSDS (Material Safety Data Sheet)** is the reference document type implemented throughout this book — hence the naming convention `MSDS_VECTORS`, `MSDS_Graph`. The architecture, ingestion pipeline, and query orchestration are document-type agnostic. Swap the knowledge graph extraction prompt and the pattern applies to batch quality certificates, inspection reports, maintenance manuals, or any document class you need.

---

## 1.2 Why Hybrid Retrieval — Not Just Search

When a safety officer asks about storage requirements for a chemical, the answer exists somewhere in an MSDS. But that question actually demands two fundamentally different kinds of retrieval, and this distinction is what drives the entire architecture of this system.

**Documents contain two kinds of content.**

The first kind is **structured facts**: GHS hazard category codes, UN transport numbers, flash points in degrees Celsius, permissible exposure limits in mg/m³, certification dates, batch lot numbers, compliance standard references (REACH, CLP, OSHA). These are discrete, precise values. The right answer to *"What is the flash point of acetone?"* is *"-20°C"* — not a paragraph that mentions temperature somewhere.

The second kind is **narrative prose**: first-aid procedures, personal protective equipment recommendations, handling and storage guidance, ecological impact descriptions, disposal instructions. These are sentences and paragraphs written in natural language. The right answer to *"What should I do if someone inhales acetone vapour?"* is a passage from Section 4 of the MSDS — and finding it requires understanding semantic meaning, not matching keywords.

**Vector search alone fails on structured facts.** Ask for a GHS hazard code and vector search returns the chunk with the highest cosine similarity to your query — often around 0.65 — which may or may not contain the specific code. There is no guarantee of precision. You might retrieve a chunk that discusses GHS categories generally without stating the specific code for your material.

**A knowledge graph alone fails on narrative questions.** A SPARQL query returns triples — subject, predicate, object — from the RDF graph. It can answer *"Give me the flash point of CHEMICAL-001"* in one query. It cannot answer *"Describe the first-aid procedure for skin contact with CHEMICAL-001"* because that information is prose, not a fact that maps cleanly to a triple.

**SAP HANA Cloud is the only managed database service that provides both in one instance.** `REAL_VECTOR` cosine similarity search for semantic retrieval, and SPARQL 1.1 endpoint (`SPARQL_EXECUTE`) for graph queries — same HANA instance, same network hop, same connection pool. No separate vector database, no separate graph store, no additional BTP service to provision.

The hybrid approach is therefore not a design preference. It is the correct response to the actual structure of enterprise documents. Run both chains in parallel. Synthesise when both return results. Defer to whichever chain returns when only one does. Acknowledge uncertainty when neither does. That is the architecture.

---

## 1.3 The Four Capabilities That Define the Agent

The system in this book is not a fixed retrieval pipeline. It makes decisions at runtime. Four specific capabilities distinguish it from a deterministic workflow.

**Tool Use**

The LangGraph orchestrator calls external functions to answer questions. In SAP terms: the knowledge graph chain calls `SPARQL_EXECUTE` against HANA Cloud and extracts structured triples. The vector chain calls a cosine similarity search against the `MSDS_VECTORS` `REAL_VECTOR` column. Either chain can be selected, skipped, or retried based on what the query needs. The LLM does not guess — it calls the right tool.

**Memory**

State persists beyond a single request. The HANA Cloud tables and named RDF graphs are the memory layer. Once you upload an MSDS for material `800021`, its vector chunks remain in `MSDS_VECTORS` and its triples remain in `GRAPH <iri:msds-graph/MAT-800021>` across sessions, across restarts, across users. Session-level context (conversation history, intermediate tool outputs) is held in the LangGraph `StateGraph` for the duration of a query. Long-term memory is HANA. Short-term memory is the graph state.

**Planning**

The LangGraph `StateGraph` routes each query at runtime. A question phrased as *"What is the GHS hazard code?"* routes primarily to the graph chain — it is a structured fact lookup. A question phrased as *"Describe the first-aid procedure"* routes primarily to the vector chain — it is a narrative retrieval. When both chains return results, the supervisor node decides how to weight and merge them before passing to the synthesis node. The routing is not a hard-coded `if/else` — it emerges from the conditional edge logic and the confidence scores returned by each chain.

**Multi-Agent Collaboration**

The orchestrator is a supervisor agent. It delegates to two specialist sub-agents — the Vector Retrieval Agent and the Knowledge Graph Agent — each of which has its own tool set, its own HANA connection (thread-local), and its own result format. The supervisor collects both results, applies the merge strategy, and passes the combined context to Gemini 2.5 Flash for synthesis. Adding a third specialist agent (for example, an SAP OData query agent that retrieves live inventory data alongside the document answer) requires adding one node and one conditional edge to the graph.

---

## 1.4 SAP's Strategic Direction: The Autonomous Enterprise (Sapphire 2026)

The timing of this book is not coincidental. SAP has placed agentic AI at the centre of its entire product strategy, and the architecture you build here maps directly to what SAP is standardising.

At **SAP Sapphire 2026 in Orlando**, CEO Christian Klein unveiled the **Autonomous Enterprise** — a model where AI agents and human workers collaborate continuously to execute, adapt, and optimise critical business processes. Klein:

> *"For the mission-critical processes of our customers, 'almost right' just isn't good enough. By uniting SAP Business AI Platform with SAP Autonomous Suite, we anchor AI agents in the business processes, data and governance so they can deliver accurate, compliant and secure outcomes."*

The scale of what SAP announced is significant:

| Milestone | Detail |
|-----------|--------|
| **200+ specialised agents** | Available for orchestration across the SAP portfolio — Finance, Supply Chain, Procurement, HR, CX |
| **50+ Joule Assistants** | Domain-specific AI assistants embedded across S/4HANA, Ariba, SuccessFactors, and more |
| **7 Industry AI solutions** | Vertical-specific autonomous solutions through the Industry AI initiative |
| **SAP Autonomous Suite** | New product suite embedding agents directly into core SAP applications |
| **Joule Studio** | No-code and pro-code environment on BTP for building custom agents |
| **€100 million partner fund** | Accelerating partner deployments of AI agents across the ecosystem |

SAP also announced a partnership with **NVIDIA** — specifically the **OpenShell** secure runtime environment for Joule Studio agent execution — and the planned acquisition of **Prior Labs**, a European frontier AI research lab, signalling that SAP intends to control the AI stack from the data layer through the model layer.

**What this means for you as a BTP developer:** the 200+ agents SAP announced were not all built by SAP. Partners and customers on BTP built them using the same patterns this book teaches — LangGraph orchestration, HANA Cloud retrieval, CAP as the OData surface, Joule A2A for integration. You are building on the architecture SAP is standardising. The skills you develop here translate directly to Joule Studio, SAP Business AI Platform, and the autonomous enterprise patterns SAP's largest customers are now adopting.

---

## 1.5 What We Build: System Overview

The anchor for everything in this system is the **SAP Material Number**. It is not arbitrary — it comes from your live S/4HANA product catalogue. Before a document can be uploaded, the material number is validated against `API_PRODUCT_SRV` (SAP's standard product OData V4 service), which confirms the material exists and returns basic product attributes. This keeps the system honest: you cannot ingest a document against a material number that does not exist in your SAP system.

**Ingestion flow:**

Upload a PDF against material `800021`. The CAP OData V4 service (`/odata/v4/msds/uploadDocument`) receives the request, validates the material number, and calls the FastAPI backend (`POST /ingest`). The backend runs two ingestion tasks in parallel:

- **Vector ingestion**: The PDF is parsed, chunked (512 tokens, 50-token overlap), and each chunk is embedded with `text-embedding-004`. Embeddings and chunk text are inserted into `MSDS_VECTORS` (a HANA Cloud column table with a `REAL_VECTOR` column). Index: cosine similarity.
- **KG ingestion**: Gemini 2.5 Flash reads the full document and extracts structured triples — material identifiers, GHS codes, physical properties, regulatory standards, certifying bodies, dates. Triples are written to HANA Cloud as RDF in the named graph `GRAPH <iri:msds-graph/MAT-800021>` using `SPARQL_EXECUTE`.

Both run in a `ThreadPoolExecutor`. Both complete before the response returns to the CAP layer.

**Query flow:**

The user types a question in the Fiori Elements chat UI. The CAP service proxies it to the FastAPI backend (`POST /query`). The LangGraph supervisor node initialises a `StateGraph` and fans out to both chains in parallel:

- The **Vector Chain** embeds the question, runs cosine similarity search against `MSDS_VECTORS` for the target material, and returns the top-k chunks with similarity scores
- The **KG Chain** converts the question to a SPARQL SELECT query, executes it against `SPARQL_EXECUTE` on the named graph, and returns structured triples

The supervisor merge node receives both result sets, formats them as context, and calls Gemini 2.5 Flash with a synthesis prompt that instructs the model to cite the source (vector chunk reference or graph triple) for every claim in the answer. The cited answer returns to the Fiori UI.

**UI and deployment:**

The Fiori Elements UI is generated entirely from the CAP OData V4 annotations — no custom frontend code. The chat page uses a `sap.fe` freestyle page with standard SAPUI5 controls. The CAP service (`cds serve`) runs on port 4004. The FastAPI agent (`uvicorn main:app`) runs on port 8000. In Chapter 10, both are deployed to BTP Cloud Foundry. The CAP service is deployed as a single MTA, the FastAPI service as a Python CF application.

![Agentic Hybrid RAG System Architecture](docs/screenshots/diagrams/02-agentic-rag-overview.png)

*Figure 1.1 — Material Number is the anchor. Documents are ingested into MSDS_VECTORS (vector) and MSDS_Graph/MAT-{material} (RDF) in parallel. Queries fan out to both chains, merge, and synthesise a cited answer via Gemini 2.5 Flash.*

---

## 1.6 Why MSDS First

MSDS documents are the ideal worked example for this architecture, for one specific reason: they contain both kinds of retrievable content in roughly equal proportion.

Section 1 of an MSDS (Product Identification), Section 2 (Hazard Identification), Section 9 (Physical and Chemical Properties), and Section 15 (Regulatory Information) are structured fact stores. They contain GHS hazard category codes, signal words, UN transport numbers, flash points, boiling points, permissible exposure limits, and references to specific regulatory standards (REACH Regulation EC 1907/2006, OSHA 29 CFR 1910.1200, CLP Regulation EC 1272/2008). These facts map directly to RDF triples: `<CHEMICAL-001> ghs:hazardCategory "Flammable Liquids Cat. 2"`.

Section 4 (First-Aid Measures), Section 6 (Accidental Release Measures), Section 7 (Handling and Storage), Section 8 (Exposure Controls / PPE), and Section 13 (Disposal Considerations) are narrative prose. They cannot be decomposed into triples without losing their meaning. A first-aid procedure for inhalation exposure is a paragraph, not a fact. Vector search with cosine similarity finds it correctly.

A quality or safety professional asking questions about an MSDS needs answers from both halves in the same conversation. *"Is this chemical classified as a flammable liquid?"* — graph. *"What PPE should maintenance staff wear when handling it?"* — vector. *"What is the flash point, and at what concentrations does it become a fire risk?"* — graph for the flash point, vector for the concentration narrative.

Any manufacturing, chemical, pharmaceutical, or industrial company operating on SAP has hundreds of MSDS documents. The legal obligation to have them accessible is explicit (REACH, GHS, OSHA). The technical debt of managing them in scattered file systems is universal.

The architectural pattern built here transfers directly to other document types:

| Document Type | Graph Content (structured) | Vector Content (narrative) |
|---------------|---------------------------|---------------------------|
| Batch Quality Certificate | Lot number → test result → specification | Test methodology descriptions |
| Supplier Invoice | Vendor → line item → material → amount | Payment terms, dispute notes |
| Equipment Maintenance Record | Asset → service action → date → technician | Failure description, root cause narrative |
| Goods Receiving Inspection Report | Batch → inspection result → QM usage decision | Inspector observations |
| Regulatory Compliance Filing | Standard → obligation → deadline → status | Compliance justification text |

Change the KG extraction prompt to match the document type's ontology. The vector chunking, HANA ingestion, LangGraph orchestration, and CAP OData layer are unchanged.

---

## 1.7 Scope and Prerequisites

### What This Book Covers

| Topic | Coverage |
|-------|----------|
| SAP document fragmentation problem and BTP solution architecture | Full coverage, Ch 1 |
| SAP BTP trial setup — HANA Cloud, CF space, Destination Service | Full coverage, Ch 2 |
| Vector search on HANA Cloud (REAL_VECTOR, cosine similarity) | Full coverage, Ch 3 |
| Knowledge graphs on HANA Cloud (SPARQL/RDF, named graphs) | Full coverage, Ch 4 |
| PDF ingestion pipeline — parallel KG + vector with ThreadPoolExecutor | Full coverage, Ch 5 |
| LangGraph — StateGraph, nodes, conditional edges, routing | Full coverage, Ch 6 |
| Hybrid RAG agent — parallel chains, merge strategy, synthesis | Full coverage, Ch 7 |
| Multi-agent supervisor pattern — specialist sub-agents | Full coverage, Ch 8 |
| CAP Node.js OData V4 service + Fiori Elements UI | Full coverage, Ch 9 |
| Deploying to SAP BTP Cloud Foundry (MTA + cf push) | Full coverage, Ch 10 |
| Joule A2A integration (enterprise subscription required) | Appendix D |
| SAP AI Core as LLM alternative | Appendix E |
| MSDS ontology design (OWL/Turtle) | Appendix B |
| HANA Cloud SPARQL reference | Appendix C |

### What This Book Does NOT Cover

**Production hardening.** Rate limiting, multi-tenant isolation, secrets rotation, disaster recovery, and SLA monitoring are not covered. This book teaches architecture and implementation patterns, not operations.

**Model training or fine-tuning.** All LLM usage is inference-only — calling hosted models via API.

**Cross-material reasoning.** The agent answers questions about one material's documents at a time. Cross-material aggregation (e.g. *"Which of our chemicals in this plant require respiratory PPE?"*) is a natural extension not covered here.

**Streaming responses.** Answers are returned synchronously as complete text.

**CI/CD pipelines.** Chapter 10 uses manual `cf push` and `mbt build && cf deploy`.

**Joule and SAP AI Core on free trial.** Both require paid SAP subscriptions. They are in Appendices D and E so enterprise readers can follow along without blocking the main chapters.

### Prerequisites

| Requirement | Where to Get It | Cost |
|-------------|----------------|------|
| SAP BTP Trial account | account.hanatrial.ondemand.com | Free |
| SAP HANA Cloud trial instance | BTP Trial cockpit → HANA Cloud tile | Free (30-day) |
| GCP account with Vertex AI enabled | cloud.google.com/free | Free ($300 credit) |
| Python 3.11+ | python.org | Free |
| Node.js 20+ and npm | nodejs.org | Free |
| CF CLI v8+ | CF documentation | Free |
| `@sap/cds` CLI (`npm i -g @sap/cds`) | npm | Free |
| VS Code with SAP CDS extension | code.visualstudio.com | Free |

Chapter 2 covers every setup step with screenshots. If you already have an active BTP trial and GCP project, setup takes roughly 30 minutes.

**Local development is the primary mode for Chapters 1–9.** You run `uvicorn main:app --reload` for the FastAPI agent and `cds serve` for the CAP service on your local machine, both connecting to your BTP HANA Cloud trial instance. Chapter 10 deploys the same code to Cloud Foundry — nothing changes except where it runs.

---

## 1.8 Summary

- Standard SAP has no transaction that stores all material-linked documents in one place and makes them intelligently queryable. Documents are scattered across shared drives, email, DMS, and plant servers. This is a structural gap in SAP's portfolio that BTP is built to fill.
- This book builds an Agentic Hybrid RAG Document Intelligence Platform: upload PDFs against an SAP Material Number, ingest to HANA Cloud vector store and RDF knowledge graph simultaneously, query both in parallel, synthesise cited answers via Gemini 2.5 Flash.
- Hybrid retrieval is not a design choice — it is the correct response to the structure of enterprise documents. Structured facts (GHS codes, batch numbers, flash points, compliance standards) need SPARQL exact lookup. Narrative prose (procedures, descriptions, instructions) needs vector cosine similarity. HANA Cloud provides both in one managed service.
- The system is agentic in a precise sense: it uses tools (SPARQL_EXECUTE, REAL_VECTOR search), persists memory (HANA tables and RDF graphs), plans routing at runtime (LangGraph StateGraph conditional edges), and delegates to specialist sub-agents (supervisor pattern).
- SAP announced the Autonomous Enterprise at Sapphire 2026: 200+ specialised agents, Joule Studio on BTP, SAP-NVIDIA partnership, Prior Labs acquisition. The architecture this book teaches is the same architecture SAP is standardising.
- MSDS is the reference document type because it contains structured facts and narrative prose in equal measure — ideal for demonstrating both retrieval chains. The same architecture transfers to batch certificates, invoices, inspection reports, and maintenance records by changing only the KG extraction prompt.
- The full stack runs at zero cost: SAP BTP trial + Google Cloud $300 free credit.

Chapter 2 sets up the platform: BTP trial, HANA Cloud instance, GCP project, and Vertex AI credentials. By the end of Chapter 2 you have a working environment and can run your first HANA vector insert.
