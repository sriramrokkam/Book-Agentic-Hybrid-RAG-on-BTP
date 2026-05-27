# Chapter 1: Agentic AI on SAP BTP — What It Is, Why It Matters, and What We Build

## 1.1 The Agentic AI Moment

An AI agent is not a chatbot. A chatbot takes a question and returns a response — it is a single-turn input/output system. A copilot offers suggestions inline with your work, but a human makes every consequential decision. An AI agent is something categorically different: it accepts a goal, selects tools, executes a sequence of steps, evaluates intermediate results, and revises its plan — autonomously — until the goal is reached or it determines it cannot.

Four capabilities define whether a system is genuinely agentic. Understanding them precisely is worth the time before a single line of code is written.

**Tool Use** is the ability to call external functions — APIs, databases, search engines, file systems — and incorporate the results into the next step of reasoning. In an SAP context: imagine an agent that, when asked about the status of a purchase order, does not guess from training data but calls `API_PURCHASEORDER_PROCESS_SRV` directly, reads the live document flow, checks delivery confirmation in the GR table, and returns a current answer. The LLM is not the knowledge store — it is the reasoning engine that decides what to call and what to do with the result.

**Memory** is the ability to retain information across steps and across sessions. Short-term memory is the working state of a task in progress — the list of tool outputs so far, the intermediate reasoning, the partial answer. Long-term memory is a persistent store that survives restarts — a database, a vector table, a knowledge graph. In an SAP context: an agent that has ingested a supplier's quality certificates stores those embeddings in HANA Cloud. Next week, when a quality engineer asks about that supplier's latest batch result, the agent retrieves from long-term memory rather than asking for the document again.

**Planning** is the ability to decompose a goal into a sequence of steps and revise that sequence based on what intermediate steps return. A deterministic workflow executes the same path every time. A planning agent determines at runtime — based on the question, the available tools, and the results so far — what step to take next. In an SAP context: an agent handling a supplier qualification query might first retrieve open inspection reports, then — if those reports contain anomalies — automatically invoke a second tool to check whether a corrective action request exists in QM before composing its answer.

**Multi-Agent Collaboration** is the ability to delegate subtasks to specialist agents and synthesise their outputs. A supervisor agent receives a complex goal and routes parts of it to agents with focused expertise: one agent that specialises in document retrieval, another that queries live ERP data, another that generates a structured report. Each specialist operates independently and returns results to the supervisor, which merges them into a coherent answer. In an SAP context: the supervisor delegates "retrieve batch quality data" to the KG agent, "retrieve supplier invoice details" to the vector agent, and "look up the purchase order" to an OData agent — then synthesises all three into a single procurement audit response.

These four capabilities are not a theoretical framework. They are the design vocabulary for the system built in this book, and they map directly to the implementation choices made at every layer of the stack.

---

## 1.2 Why SAP Developers Need to Understand Agents Now

SAP is not approaching agentic AI cautiously. At **SAP Sapphire 2026 in Orlando**, CEO Christian Klein placed agents at the centre of the company's entire product strategy under the banner of the **Autonomous Enterprise** — a model where AI agents and human workers collaborate continuously to execute, adapt, and optimise critical business processes. Klein:

> *"For the mission-critical processes of our customers, 'almost right' just isn't good enough. By uniting SAP Business AI Platform with SAP Autonomous Suite, we anchor AI agents in the business processes, data and governance so they can deliver accurate, compliant and secure outcomes."*

The announcements at Sapphire 2026 were not roadmap items. They were generally available or in ramp-up:

| Milestone | Detail |
|-----------|--------|
| **200+ specialised agents** | Available across Finance, Supply Chain, Procurement, HR, and CX — built on the same BTP agent patterns this book teaches |
| **50+ Joule Assistants** | Domain-specific AI assistants embedded across S/4HANA, Ariba, SuccessFactors, and more |
| **SAP Autonomous Suite** | New product suite embedding agents directly into core SAP applications |
| **Joule Studio on BTP** | No-code and pro-code environment for building custom agents on SAP BTP |
| **NVIDIA OpenShell partnership** | Secure runtime environment for Joule Studio agent execution |
| **Prior Labs acquisition** | European frontier AI research lab — SAP acquiring capability to control the AI stack from data layer to model layer |
| **€100 million partner fund** | Accelerating partner deployments of AI agents across the ecosystem |

The implication for BTP developers is direct: the 200+ agents SAP announced were not all built inside SAP. Partners and customers on BTP built them. The patterns used — LangGraph-style orchestration, HANA Cloud retrieval, CAP as the OData surface, Joule Agent-to-Agent (A2A) for integration with the broader SAP agent ecosystem — are the same patterns this book teaches.

SAP is standardising an agent architecture. Joule Studio is the no-code surface, but below Joule Studio is a pro-code layer on Cloud Foundry that looks exactly like what you build here: a Python orchestration service, a HANA Cloud retrieval backend, a CAP service that exposes the capability as OData V4. The patterns in this book are not theoretical preparation for a future SAP platform. They are the current architecture that SAP's largest customers and partners are building on today.

An SAP developer who understands ABAP, CDS views, BTP integration, and the core SAP data model has the right foundation. What is new is the orchestration layer — how to structure an agent that uses tools rather than calling APIs directly, how to design a retrieval architecture that handles both structured and unstructured enterprise content, and how to connect that agent to the SAP surface your business users already work in. That is what this book teaches.

---

## 1.3 Why BTP Is the Right Platform for Agentic AI

A common question from BTP developers encountering agentic AI for the first time is whether they need to move off BTP to build it — whether this work belongs on a specialist ML platform, in a dedicated vector database, or behind a separate AI infrastructure layer. It does not. BTP already has what you need, and in one important dimension it has something no other cloud platform offers.

**HANA Cloud is uniquely positioned.** Every other cloud-native vector store is a specialised service: Pinecone, Weaviate, ChromaDB, AlloyDB pgvector. They provide semantic similarity search against embeddings. HANA Cloud provides that — the `REAL_VECTOR` column type with cosine similarity search — and also provides a full SPARQL 1.1 endpoint (`SPARQL_EXECUTE`) for RDF knowledge graph queries, in the same managed database instance, on the same network hop from your Cloud Foundry application. No other managed database available on a major cloud provider combines production-grade vector search with a compliant SPARQL endpoint in a single service. On BTP, this combination costs nothing beyond the trial credit to provision. You do not need a separate graph store. You do not need a separate vector database. One HANA Cloud instance handles both retrieval chains.

**CAP gives you a production OData V4 service and Fiori Elements UI in minutes.** Without CAP, connecting an agent backend to a Fiori frontend requires building an OData service layer manually — schema definition, entity framework, routing, error handling, authentication. With CAP, you define your entities in CDS, annotate them for Fiori Elements, and `cds serve` gives you a functional OData V4 service. The Fiori Elements UI is generated from annotations — no custom frontend code. The CAP layer handles XSUAA authentication when you deploy to Cloud Foundry. For an SAP developer, this is already familiar territory.

**The Destination Service externalises enterprise credentials properly.** Connecting to S/4HANA from BTP is solved infrastructure: you configure a Destination in the BTP cockpit with the S/4HANA credentials, and your application reads the destination at runtime without hardcoding credentials. For `API_PRODUCT_SRV` — the OData service used to validate material numbers against the live product master — this means your agent never holds S/4HANA credentials directly. The Destination Service is a first-class BTP service, not a workaround.

**Cloud Foundry runtime runs Python and Node.js side by side.** The system in this book consists of two services: a Python FastAPI application running the LangGraph orchestrator (port 8000) and a CAP Node.js service (port 4004). Both are deployed to the same CF space as separate applications. They communicate over HTTP. CF handles scaling, restarts, environment variable injection, and service binding. The deployment in Chapter 10 uses a single MTA descriptor that captures both applications and their HANA Cloud service binding.

**You do not need SAP AI Core.** SAP AI Core is the enterprise ML platform on BTP — it provides managed model deployment, training pipelines, and the foundation model access layer used by Joule. It requires an enterprise subscription that is not available on a BTP trial account. This book uses Vertex AI (Google Cloud) as the LLM and embedding provider. Vertex AI provides Gemini 2.5 Flash for synthesis and text-embedding-004 for embedding generation. Both are available under the Google Cloud $300 free credit, and the free tier is sufficient for the entire development cycle in Chapters 1 through 9. For readers with access to SAP AI Core, Appendix E covers how to swap the LLM provider; the agent architecture is unchanged.

The combination — HANA Cloud dual retrieval, CAP OData surface, Destination Service credential management, CF runtime for Python and Node.js, Vertex AI for model inference — gives a BTP developer a complete agentic AI stack that requires no additional infrastructure, no new platform to learn, and no production-tier subscription to get started. The platform you already work on is the right platform.

---

## 1.4 What This Book Builds: The Material Document Intelligence Platform

The worked example throughout this book is a **Material Document Intelligence Platform**: a system that accepts any PDF document linked to an SAP Material Number, ingests it into HANA Cloud, and answers natural-language questions about it using a LangGraph hybrid RAG agent surfaced through a Fiori Elements UI.

This platform is the teaching vehicle, not the subject of the book. Each chapter introduces a concept — vector search, knowledge graph retrieval, LangGraph orchestration, multi-agent supervision, CAP integration, CF deployment — and builds the corresponding component of the platform. By Chapter 10, the pieces form a running system.

**The anchor: SAP Material Number**

Every document in the system is linked to an SAP Material Number — the unique identifier that appears in MM03, in goods movements, in quality inspection lots, in purchase orders. Before a document is accepted for ingestion, the material number is validated against `API_PRODUCT_SRV`, SAP's standard product OData V4 service. This validation confirms the material exists in your S/4HANA product master and returns basic product attributes (material description, base unit, material group). The system will not ingest a document against a material number that does not exist in SAP. The anchor is live data, not a local list.

**Document types supported**

The platform is designed to handle any PDF document type that an SAP user would associate with a material. The reference implementation covers five document types:

- **Batch Quality Certificates** — supplier-issued documents confirming test results against specification for a specific production batch
- **Goods Receiving Inspection Reports** — QM-generated reports recording the outcome of incoming goods inspection, including usage decision and lot status
- **Equipment Maintenance History** — service records linked to technical objects (equipment numbers) associated with materials in plant maintenance
- **Supplier Invoices** — AP documents linking vendor, line items, purchase order references, and payment terms
- **MSDS (Material Safety Data Sheets)** — standardised regulatory documents describing material properties, hazard classification, and handling requirements

MSDS is the document type used for the reference implementation. The HANA Cloud vector table is named `MSDS_VECTORS`. The HANA RDF named graph is `MSDS_Graph`. Test data, sample queries, and the ontology in Appendix B are all MSDS-based. This is a naming artifact from the reference implementation, not a constraint on the architecture. The ingestion pipeline, agent orchestration, and retrieval logic are document-type agnostic. Changing the knowledge graph extraction prompt — the instruction that tells Gemini 2.5 Flash what triples to extract — is all that is required to apply the same system to batch certificates, inspection reports, or maintenance records. The table naming is explained once, accepted throughout, and not revisited.

**Ingestion: parallel vector and graph**

When a user uploads a PDF against a material number, the FastAPI backend runs two ingestion tasks in parallel using `ThreadPoolExecutor`:

The vector ingestion task parses the PDF, chunks the text at 512 tokens with 50-token overlap, and embeds each chunk using `text-embedding-004`. Chunk text and embeddings are inserted into `MSDS_VECTORS`, a HANA Cloud column table with a `REAL_VECTOR` column. The HANA cosine similarity index operates over this column.

The knowledge graph ingestion task sends the full document text to Gemini 2.5 Flash with a structured extraction prompt. The model extracts RDF triples — entities, relationships, and attribute values — and returns them as Turtle syntax. The triples are written to HANA Cloud using `SPARQL_EXECUTE` into the named graph `GRAPH <iri:msds-graph/MAT-{material}>`. Each material gets its own named graph, isolating its triples from other materials' data.

Both tasks complete before the ingestion response returns to the CAP layer. The CAP service logs the ingestion outcome and returns a confirmation to the Fiori UI.

**Query: parallel retrieval, merge, synthesise**

When a user submits a question through the Fiori chat UI, the CAP service proxies it to the FastAPI backend. The LangGraph supervisor node initialises a `StateGraph` and fans out to both retrieval chains in parallel:

The Vector Chain embeds the question using `text-embedding-004`, runs cosine similarity search against `MSDS_VECTORS` filtered to the target material, and returns the top-k matching chunks with similarity scores.

The KG Chain converts the question into a SPARQL SELECT query, executes it against `SPARQL_EXECUTE` on the material's named graph, and returns structured triples.

The supervisor merge node receives both result sets. It formats the vector chunks and graph triples as a combined context block and calls Gemini 2.5 Flash with a synthesis prompt that requires the model to cite the source of every claim — either by chunk reference (vector) or by triple predicate (graph). The cited answer is returned to the Fiori UI.

**Architecture: two services, one platform**

The system consists of two services communicating over HTTP:

- **FastAPI agent** (`uvicorn main:app`, port 8000): the LangGraph orchestrator, ingestion pipeline, HANA Cloud connections (thread-local), and all LLM calls
- **CAP service** (`cds serve`, port 4004): OData V4 entities, Fiori Elements UI, S/4HANA material number validation via Destination Service, proxying to the FastAPI backend

In local development, both run on your machine and connect to the HANA Cloud trial instance over JDBC. In Chapter 10, both are deployed to the same BTP Cloud Foundry space — CAP as an MTA, FastAPI as a Python CF application — and the HANA Cloud service binding is injected at runtime via `VCAP_SERVICES`.

![Agentic Hybrid RAG System Architecture](docs/screenshots/diagrams/02-agentic-rag-overview.png)

*Figure 1.1 — Material Number is the anchor. Documents are ingested into MSDS_VECTORS (vector) and MSDS_Graph/MAT-{material} (RDF) in parallel. Queries fan out to both chains, merge, and synthesise a cited answer via Gemini 2.5 Flash.*

---

## 1.5 Why Hybrid Retrieval

The hybrid retrieval architecture — running vector search and SPARQL graph queries in parallel and merging the results — is not a design preference. It is the correct response to the structure of enterprise documents. Understanding why requires looking at what enterprise documents actually contain.

**Enterprise documents contain two fundamentally different kinds of content.**

The first kind is structured facts: discrete, precise values that have a single correct answer. A batch quality certificate contains the certificate number, the batch lot number, the material specification reference, the measured test values for each test parameter, the pass/fail result for each test, the certifying laboratory, and the certification date. A goods receiving inspection report contains the inspection lot number, the usage decision code (accept/reject/block), the quantity inspected, the sampling procedure, and the inspection date. An equipment maintenance record contains the functional location, the equipment number, the service action code, the work order number, the technician ID, and the completion date.

For this kind of content, the right retrieval mechanism is exact lookup. When a quality engineer asks "What is the certificate number for batch BATCH-2024-0871?" the answer is a specific identifier — one value, no ambiguity. Vector search is the wrong tool for this question. A cosine similarity search against text embeddings will return the chunk with the highest semantic similarity to the query, which might be around 0.65 — a correct-seeming paragraph that mentions certificate numbers in general without necessarily containing the specific number for that specific batch. There is no guarantee of precision. The exact fact may be embedded in a low-similarity chunk because the surrounding text is not thematically similar to the query.

The SPARQL knowledge graph answers this question correctly and deterministically. The batch quality certificate's triples include `<BATCH-2024-0871> qm:certificateNumber "CERT-2024-58291"`. A SPARQL SELECT query against the named graph for that material returns the value in one round-trip. No ambiguity, no similarity scoring, no chunk retrieval.

The second kind of content is narrative prose: sentences and paragraphs written in natural language that convey meaning through context, not through discrete values. A batch quality certificate's methodology section describes how each test was conducted — the equipment used, the test conditions, the standard procedure referenced, the inspector's observations about any anomalies. A goods receiving inspection report includes the inspector's narrative description of the physical condition of the goods, observations about packaging integrity, and the qualitative rationale for the usage decision. An equipment maintenance record includes the technician's description of the fault found, the diagnosis, and the repair approach.

For this kind of content, the right retrieval mechanism is semantic similarity search. When a quality engineer asks "How did the supplier describe the tensile strength testing method on this batch?" the answer is a passage of prose. SPARQL cannot answer it — there is no triple that captures a methodology description without losing the meaning carried by the narrative. Vector search finds it correctly: the question's embedding is semantically close to the chunk that describes the test methodology, and cosine similarity search returns it.

**HANA Cloud is the only managed database on BTP that provides both.**

`REAL_VECTOR` cosine similarity search handles the narrative questions. `SPARQL_EXECUTE` handles the structured fact questions. Both operate against the same HANA Cloud instance — the same network hop from your Cloud Foundry application, the same connection pool, the same service binding. No separate vector store provisioned alongside a separate graph store. No synchronisation between two external systems. No additional BTP service to configure.

The hybrid approach at runtime is straightforward: run both chains in parallel, merge the results, instruct the synthesis model to cite the source of each claim. When both chains return results, the answer draws on both. When only one chain returns results — because the question is purely factual or purely narrative — the answer draws on that chain. When neither chain returns results above a confidence threshold, the agent acknowledges it could not find the answer rather than generating a plausible-sounding fabrication.

That is the architecture, and Chapter 7 builds it in full.

---

## 1.6 The Four Agentic Capabilities in This System

Section 1.1 defined four capabilities that distinguish an AI agent from a deterministic retrieval pipeline. Here is how each maps to the actual implementation built in this book.

**Tool Use**

The LangGraph orchestrator calls HANA Cloud as an external tool — twice, via two different interfaces. The KG Chain issues a `SPARQL_EXECUTE` call against the named graph for the target material. The Vector Chain issues a `REAL_VECTOR` cosine similarity query against `MSDS_VECTORS`. Neither call is hardcoded into a fixed pipeline. The LangGraph `StateGraph` decides at runtime, based on the structure of the question and the routing logic encoded in the conditional edges, which tools to call and in what configuration. When a question is structured as a precise fact lookup, the KG Chain is weighted more heavily. When a question is framed as an open descriptive query, the Vector Chain carries more weight. The LLM does not serve as the knowledge store — it calls the right tool and synthesises from what the tool returns.

**Memory**

Memory in this system operates at two timescales. Long-term memory is HANA Cloud: the `MSDS_VECTORS` table persists vector embeddings across sessions, across restarts, and across users. The named RDF graphs in `MSDS_Graph` persist triples for every ingested document. Once a batch quality certificate is ingested for material `800021`, its vector chunks and its triples are available to every subsequent query — no re-ingestion, no re-embedding, no warm-up time. Short-term memory is the LangGraph `StateGraph`: for the duration of a single query, the state object holds the conversation history, the intermediate tool outputs from both retrieval chains, the merge strategy output, and the synthesis context. When the query completes, the state is discarded. Long-term memory is HANA. Short-term memory is the graph state.

**Planning**

The LangGraph `StateGraph` routes each query at runtime through conditional edges. The supervisor node evaluates the incoming question and the results returned by the retrieval chains before deciding what to do next. A question structured as "What is the usage decision for inspection lot IL-2024-0091?" routes primarily through the KG Chain — it is asking for a discrete value that maps to a triple. A question structured as "Describe the condition of the packaging as observed during incoming inspection" routes primarily through the Vector Chain — it is asking for narrative prose. A question that combines both — "What was the usage decision, and what did the inspector observe about the packaging?" — fans out to both chains and merges the results. The routing is not a hard-coded `if/else` block. It emerges from the conditional edge logic and the confidence scores returned by each chain. Chapter 6 builds the `StateGraph` and its routing logic from scratch.

**Multi-Agent Collaboration**

The supervisor pattern in Chapter 8 implements multi-agent collaboration explicitly. The supervisor node is the orchestrating agent. It delegates to two specialist sub-agents: the Vector Retrieval Agent, which owns the `MSDS_VECTORS` table interaction and the embedding pipeline, and the Knowledge Graph Agent, which owns the HANA SPARQL endpoint and the triple extraction logic. Each specialist has its own HANA connection (thread-local, to avoid connection sharing across threads), its own tool set, and its own result format. The supervisor collects the results from both specialists, applies the merge strategy, and passes the combined context to Gemini 2.5 Flash for synthesis. The architecture is extensible: adding a third specialist — for example, an OData agent that retrieves live inventory data from S/4HANA via `API_MATERIAL_STOCK_SRV` — requires adding one node and one conditional edge to the graph. The supervisor pattern does not change.

---

## 1.7 Scope and Prerequisites

### What This Book Covers

| Topic | Coverage |
|-------|----------|
| Agentic AI concepts — tool use, memory, planning, multi-agent collaboration | Full coverage, Ch 1 |
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

### What This Book Does Not Cover

**Production hardening.** Rate limiting, multi-tenant isolation, secrets rotation, disaster recovery, and SLA monitoring are not covered. This book teaches architecture and implementation patterns, not operations.

**Model training or fine-tuning.** All LLM usage is inference-only — calling hosted models via API. No training pipelines, no fine-tuned models, no custom embeddings.

**Cross-material reasoning.** The agent answers questions about one material's documents at a time. Cross-material aggregation — for example, "Which materials in this plant have open corrective action requests in the past 90 days?" — is a natural extension not covered here.

**Streaming responses.** Answers are returned synchronously as complete text. Streaming via Server-Sent Events is not implemented.

**CI/CD pipelines.** Chapter 10 uses manual `cf push` and `mbt build && cf deploy`. Automated deployment pipelines are not covered.

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

**Local development is the primary mode for Chapters 1–9.** You run `uvicorn main:app --reload` for the FastAPI agent and `cds serve` for the CAP service on your local machine, both connecting to your BTP HANA Cloud trial instance over JDBC. Chapter 10 deploys the same code to Cloud Foundry — nothing changes except where it runs.

---

## 1.8 Summary

- An AI agent is distinguished from a chatbot or copilot by four capabilities: tool use, memory, planning, and multi-agent collaboration. These are not theoretical distinctions — they map directly to specific implementation choices in the LangGraph orchestration, HANA Cloud retrieval, and supervisor pattern built in this book.
- SAP announced the Autonomous Enterprise at Sapphire 2026: 200+ specialised agents, Joule Studio on BTP, the NVIDIA OpenShell partnership, and the Prior Labs acquisition. The agent architecture patterns in this book — LangGraph orchestration, HANA Cloud retrieval, CAP as OData surface, Joule A2A — are the same patterns SAP is standardising across its platform.
- SAP BTP is the right platform for agentic AI development because HANA Cloud provides vector search and SPARQL graph queries in a single managed service — a combination that no other managed database on a major cloud platform offers. CAP, the Destination Service, and Cloud Foundry complete the stack. SAP AI Core is not required; Vertex AI fills the model inference role on the free tier.
- The worked example is a Material Document Intelligence Platform: upload PDFs against an SAP Material Number validated via `API_PRODUCT_SRV`, ingest to `MSDS_VECTORS` and `MSDS_Graph` in parallel via `ThreadPoolExecutor`, query both with a LangGraph hybrid RAG agent, synthesise a cited answer via Gemini 2.5 Flash, surface it through Fiori Elements. The document types supported include Batch Quality Certificates, GR Inspection Reports, Equipment Maintenance History, Supplier Invoices, and MSDS. Table names use MSDS as a naming convention from the reference implementation.
- Hybrid retrieval is the correct architecture for enterprise documents because those documents contain two kinds of content that require different retrieval mechanisms. Structured facts — certificate numbers, batch lot numbers, test results, usage decisions, inspection dates — need SPARQL exact lookup via `SPARQL_EXECUTE`. Narrative prose — methodology descriptions, inspector observations, handling instructions, qualitative assessments — needs vector cosine similarity search against `REAL_VECTOR`. HANA Cloud provides both in one instance.
- The four agentic capabilities map directly to the implementation: tool use is `SPARQL_EXECUTE` and `REAL_VECTOR` calls made by the LangGraph agent; memory is HANA Cloud long-term storage and `StateGraph` short-term context; planning is the conditional edge routing logic in the `StateGraph`; multi-agent collaboration is the supervisor pattern that delegates to Vector Agent and KG Agent and merges their results.

Chapter 2 sets up the platform: BTP trial, HANA Cloud instance, GCP project, and Vertex AI credentials. By the end of Chapter 2 you have a working environment and can run your first HANA vector insert.
