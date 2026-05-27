# Book Outline
## Agentic Hybrid RAG on SAP BTP
### A Hands-On Guide with LangGraph, HANA Cloud, and Google Vertex AI
**Author:** Sriram Rokkam

---

## The Running Example

Every chapter builds on a single real-world use case:

> **MSDS/SDS (Material Safety Data Sheets) for SAP customers**
>
> Manufacturing, chemical, pharma, and logistics companies on SAP manage thousands
> of safety documents. These contain precise structured facts (GHS codes, hazard
> classifications, exposure limits) AND dense narrative text (handling procedures,
> first aid, disposal instructions). No single retrieval strategy handles both well.
> This book builds a system that does.

---

## Chapter 0: Front Matter
`docs/chapters/chapter-00-front-matter.md`

- Title Page + Copyright
- Dedication *(author to complete)*
- Foreword *(to be written by SAP/industry contact after book completion)*
- Preface — author's voice, why this book exists *(author to personalize)*
- Who This Book Is For
- Who This Book Is NOT For
- Prerequisites — knowledge + tools (all free)
- How to Use This Book — chapter structure explained
- Conventions Used in This Book
- Acknowledgements *(author to complete)*
- About the Author *(author to complete)*

---

## Part I — Foundations

### Chapter 1: Welcome to the Agentic Era
**Key question:** What is the agentic AI shift, and what does it mean to build domain-specific agents?

- The shift: from LLMs that answer to agents that reason and act
- The agent spectrum: traditional code → workflow → RAG → autonomous agent
- Types of agents — and why domain-specific agents are the right choice for enterprise
- Why general-purpose AI is not enough: the GHS code problem as a concrete example
- Hybrid RAG as the architecture for domain-specific agents
- What this book builds: the MSDS Hybrid RAG Agent on SAP BTP
- Why now: SAP's 200+ specialist agents and the Autonomous Enterprise

**What reader can do after this chapter:** Explain what a domain-specific agent is, articulate why hybrid RAG is the right retrieval architecture, and describe what they will build in this book.

---

### Chapter 2: What Is Agentic AI — And Why SAP Developers Should Care
**Key question:** What makes an AI system "agentic" vs a plain LLM call, and why does SAP data make it powerful?

- The chatbot trap — why passive AI is not enough for enterprise problems
- The four pillars: tool use, memory, planning, multi-agent collaboration
- Why SAP data is perfect for agentic systems — richness, structure, complexity
- SAP's strategic direction: Autonomous Enterprise, Sapphire 2026, 200+ agents
- Scope of this book: what is covered, what is not, local development as primary mode
- The free stack: BTP trial + GCP $300 credit

**What reader can do after this chapter:** Understand the SAP-specific case for agentic AI, the book's full scope, and be ready to set up their environment.

---

### Chapter 3: Platform Setup — SAP BTP Trial + Google Vertex AI
**Key question:** How do I get a working environment with zero cost?

- SAP BTP trial account — signup walkthrough with screenshots
- Creating a HANA Cloud instance on BTP trial
- Enabling the HANA Cloud vector engine
- GCP account setup and $300 free credit activation
- Enabling Vertex AI API (Gemini + embeddings)
- Creating a GCP service account and downloading credentials
- SAP BTP Destination Service — connecting BTP to Vertex AI securely
- VS Code setup: Python extension, SAP CDS extension, CF tools
- Testing connectivity: first Gemini API call from BTP CF

**What reader can do after this chapter:** Have a fully working BTP + Vertex AI environment ready for development.

---

## Part II — The Knowledge Layer on SAP HANA Cloud

### Chapter 4: Vector Search on SAP HANA Cloud
**Key question:** How do I store and search document embeddings in HANA Cloud?

- What are embeddings? Intuition without the math
- HANA Cloud REAL_VECTOR column type — what it is and how it works
- Creating the vector table: lazy initialization pattern
- Calling text-embedding-004 (Vertex AI) from Python
- Storing embeddings: INSERT with REAL_VECTOR
- Cosine similarity search: the HANA SQL query explained
- Chunking strategy for MSDS documents — why chunk size matters
- Building `vector_srv.py` — the vector service layer
- Testing: upload one MSDS, search with a natural language question
- What vector search gets right — and what it gets wrong (the GHS code problem)

**What reader can do after this chapter:** Build a working vector search system on HANA Cloud, understand its strengths and limitations.

---

### Chapter 5: Knowledge Graphs on SAP HANA Cloud
**Key question:** How do I model and query structured facts as a graph?

- What is a Knowledge Graph? Triples, nodes, edges — intuition first
- RDF and SPARQL — the standards explained plainly
- Why HANA Cloud supports SPARQL (SPARQL_EXECUTE stored procedure)
- Designing the MSDS ontology — what facts matter?
  - Nodes: Material, HazardCode, ExposureLimit, Precaution, Supplier
  - Relationships: hasHazardCode, hasExposureLimit, requiresPrecaution
- The OWL ontology file: `MSDS_Ontology.ttl` explained line by line
- Extracting triples from text using Gemini (ontology-constrained prompting)
- Storing triples in HANA: named graphs per document
- Writing SPARQL queries — from natural language to graph traversal
- Building `kg_srv.py` — the Knowledge Graph service layer
- Testing: upload one MSDS, query for GHS codes via SPARQL
- What the KG gets right that vector search cannot

**What reader can do after this chapter:** Build a working Knowledge Graph on HANA Cloud, extract structured facts from documents, query via SPARQL.

---

### Chapter 6: The PDF Ingestion Pipeline
**Key question:** How do I process a document into both a vector store and a Knowledge Graph simultaneously?

- The dual-pipeline architecture — why process both in parallel
- PDF text extraction with PyMuPDF
- Chunking for vector search vs extraction for KG — different strategies
- Thread-local HANA connections — why this matters and how to implement it
- The ingestion flow:
  - Thread 1: chunk → embed → store in REAL_VECTOR
  - Thread 2: extract → validate against ontology → store as RDF triples
- Fire-and-forget pattern — upload returns immediately, processing is async
- Status tracking: dual-status in CAP schema (vectorStatus + kgStatus)
- Building `doc_srv.py` — the ingestion service
- Error handling: what happens when one pipeline fails
- Testing: upload 5 MSDS documents, verify both stores populated

**What reader can do after this chapter:** Build a production-ready document ingestion pipeline that feeds both retrieval strategies.

---

## Part III — Agentic Orchestration with LangGraph

### Chapter 7: LangGraph Fundamentals
**Key question:** What is LangGraph and how does it differ from a plain LangChain chain?

- Why LangChain chains are not enough for agentic systems
- LangGraph concepts: state, nodes, edges, conditional routing
- The StateGraph — defining your agent's memory
- Nodes — Python functions that transform state
- Edges — how the graph decides what to run next
- Conditional edges — routing based on state values
- Your first LangGraph agent: a simple question-answering loop
- Tool use in LangGraph — wrapping functions as tools
- Streaming responses — showing progress to the user
- Debugging LangGraph: LangSmith tracing setup
- Why LangGraph on BTP CF — stateless workers, no session affinity needed

**What reader can do after this chapter:** Build and run a basic LangGraph agent, understand state management and conditional routing.

---

### Chapter 8: The Parallel Hybrid RAG Agent
**Key question:** How do I run vector search and KG search in parallel and merge the results?

- The orchestrator design: always-parallel, no routing LLM call
- Why parallel beats sequential — wall-clock latency argument
- Building the vector chain:
  - Embed the question → cosine search HANA → summarize with Gemini
- Building the KG chain:
  - Gemini generates SPARQL → execute on HANA → summarize with Gemini
  - Retry-on-empty: what to do when SPARQL returns no results
- The merge function: both results → synthesis; one result → direct; none → graceful error
- ThreadPoolExecutor pattern — running both chains with a 30s timeout
- Building `orchestrator.py` — the parallel dispatch logic
- Conversation history — stateless memory passed in every request
- The `/query` endpoint — full request/response contract
- Testing: the GHS code question (KG wins) vs the precautions question (vector wins) vs a combined question (both contribute)

**What reader can do after this chapter:** Build a working hybrid RAG system that provably outperforms either retrieval strategy alone.

---

### Chapter 9: The Multi-Agent Supervisor Pattern
**Key question:** How do I scale from one agent to a system of specialist agents?

- When one agent is not enough — the complexity ceiling
- The supervisor pattern: one coordinator, multiple specialists
- Designing specialist agents for MSDS:
  - HazardAgent: GHS codes, classifications, hazard statements
  - ComplianceAgent: exposure limits, regulatory thresholds
  - SafetyAgent: precautions, first aid, PPE requirements
  - SummaryAgent: synthesize across agents
- Building the supervisor with LangGraph
- Agent handoff — passing context between agents cleanly
- Parallel vs sequential specialist execution — when each is right
- The full multi-agent flow for a complex MSDS question
- Testing: a question that requires all three specialist agents

**What reader can do after this chapter:** Build a multi-agent supervisor system, understand when to use specialist agents vs a single agent.

---

## Part IV — SAP Integration Layer

### Chapter 10: CAP Node.js OData V4 — The SAP-Native API Layer
**Key question:** How do I expose the Hybrid RAG Agent via standard SAP APIs?

- Why CAP? The standard for SAP-native services
- The CDS schema: Documents entity with dual-status tracking
- OData V4 actions — the contract between UI and backend:
  - `processFile` — trigger async ingestion
  - `pollStatus` — live progress polling
  - `chatQuery` — proxy hybrid RAG query
  - `deleteFile` — cascading delete (graph + vectors + DB)
- CAP service handlers in JavaScript — proxying to FastAPI
- Material number validation — SPARQL injection prevention
- Building the Fiori Elements UI with CAP annotations
  - List report: document inventory
  - Object page: document detail + chat interface
- Testing the OData API with SAP Business Application Studio

**What reader can do after this chapter:** Expose the Hybrid RAG Agent as a standard SAP OData V4 service with a Fiori UI.

---

### Chapter 11: Deploying to SAP BTP Cloud Foundry
**Key question:** How do I go from local development to a running BTP deployment?

- CF manifest for the FastAPI agent service
- MTA descriptor for the full CAP + HANA deployment
- BTP Destination Service — Vertex AI credentials, never in code
- Environment variables and BTP User-Provided Services
- The deployment sequence:
  1. HANA Cloud schema migration
  2. Agent service `cf push`
  3. CAP MTA `mbt build && cf deploy`
- Health checks and smoke testing after deployment
- CF logs and troubleshooting common deployment failures
- Scaling: CF instances for the agent service
- Cost reminder: everything on BTP trial is free within quota

**What reader can do after this chapter:** Deploy the complete Hybrid RAG system to SAP BTP and verify it works end-to-end in the cloud.

---

## Appendices

### Appendix A: SAP BTP Trial Setup — Step-by-Step
Complete walkthrough with screenshots:
- Creating a BTP trial account
- Navigating the BTP Cockpit
- Creating a Cloud Foundry space
- Provisioning HANA Cloud
- Enabling the vector engine on HANA Cloud
- Creating a BTP Destination for Vertex AI

### Appendix B: Google Cloud Setup — Step-by-Step
Complete walkthrough with screenshots:
- Creating a GCP account and activating $300 credit
- Creating a new GCP project
- Enabling the Vertex AI API
- Creating a service account with Vertex AI User role
- Downloading and securing the service account JSON key
- Testing: first Gemini API call from the terminal

### Appendix C: Full Code Reference
- Complete file listing for `agents/` module
- Complete file listing for `cap-srv/` module
- `MSDS_Ontology.ttl` — full OWL ontology with comments
- Sample MSDS documents used in the book (public domain)
- `.env.example` — all required environment variables

---

## Enterprise Extensions
*(Requires paid SAP subscriptions — not needed for the main book)*

### Appendix D: Joule A2A Integration
**Prerequisite:** SAP S/4HANA Cloud Public Edition or SuccessFactors subscription

- What is Joule A2A? The protocol explained
- Wrapping the Hybrid RAG Agent as a Joule capability
- The `da.sapdas.yaml` — root agent declaration
- Capability YAML, function handlers, scenario routing
- SpEL expressions — what works and what does not
- The 15-second timeout constraint — designing for Joule's limits
- Deploying a `.daar` package to SAP Joule
- Testing in the Joule sandbox

### Appendix E: Replacing Vertex AI with SAP AI Core
**Prerequisite:** SAP AI Core subscription (Standard or Extended tier)

- SAP AI Core architecture: scenarios, deployments, executions
- The three files to change: `vertex_srv.py` → `aicore_srv.py`
- AI Core LLM deployment for Gemini or GPT-4o
- AI Core embedding deployment
- BTP Destination for AI Core (replaces Vertex AI destination)
- Side-by-side: Vertex AI vs AI Core — cost, latency, features
- When to choose AI Core over Vertex AI in production

---

## Chapter Word Count Targets

| Chapter | Target Words | Target Pages |
|---------|-------------|--------------|
| Ch 1 — Welcome to the Agentic Era | 3,000 | 12 |
| Ch 2 — Why SAP Developers Should Care | 3,000 | 12 |
| Ch 3 — Platform Setup | 4,000 | 16 |
| Ch 4 — Vector Search on HANA Cloud | 5,000 | 20 |
| Ch 5 — Knowledge Graphs on HANA Cloud | 5,000 | 20 |
| Ch 6 — PDF Ingestion Pipeline | 4,000 | 16 |
| Ch 7 — LangGraph Fundamentals | 4,000 | 16 |
| Ch 8 — Parallel Hybrid RAG Agent | 5,000 | 20 |
| Ch 9 — Multi-Agent Supervisor | 4,000 | 16 |
| Ch 10 — CAP OData V4 + Fiori UI | 4,000 | 16 |
| Ch 11 — BTP Deployment | 3,000 | 12 |
| Appendices A-E | 6,000 | 24 |
| **Total** | **50,000** | **200** |

---

## 30-Day Writing Schedule

| Week | Chapters | Focus |
|------|----------|-------|
| Week 1 | Ch 1–2 + Appendix A–B | Foundations + platform setup |
| Week 2 | Ch 3–5 | Knowledge layer (code + writing) |
| Week 3 | Ch 6–8 | LangGraph agents (code + writing) |
| Week 4 | Ch 9–10 + Appendix C–E | Integration + publish |

**Daily rhythm:**
- Morning: build the code for the chapter (2–3 hrs with Claude)
- Afternoon: write the chapter explaining what we built (1–2 hrs review)
- Target: one chapter every 2–3 days

---

## Publication Plan

| Step | Tool | Deadline |
|------|------|----------|
| Write all chapters | MS Word + Claude | Day 1–25 |
| Final edit + proofread | MS Word | Day 26–27 |
| Cover design | Canva (free) | Day 26 |
| Format for Kindle | Kindle Create (free) | Day 28 |
| Upload to GitHub | github.com | Day 29 |
| Review and publish | GitHub Releases | Day 30 |

**Price target:** $9.99 Kindle / $24.99 Paperback
**GitHub repo:** All code free and open-source (drives organic discovery)
