# Chapter 1: What Is Agentic AI — And Why SAP Developers Should Care

## 1.1 Beyond the Chatbot

Most developers encounter AI for the first time as a chatbot. You type a question, the model replies. It is impressive, but it is fundamentally passive. The model waits for input, responds, and stops. It has no memory of what happened before, no ability to take action in the world, and no way to break a complex task into steps and execute them one by one.

Agentic AI changes this entirely.

An AI agent is a system where a large language model (LLM) does not just respond — it **reasons, plans, and acts**. It can call tools, retrieve information from databases, invoke APIs, hand work off to other agents, and loop back to verify its own output. The agent decides what to do next based on what it has learned so far. It is not following a fixed script. It is reasoning dynamically toward a goal.

This shift — from passive completion to active reasoning — is the most important development in applied AI since the transformer architecture itself. Foundation models gave us systems that could understand language; tools, memory, and planning loops give us systems that can act on it.

## 1.2 The Four Capabilities That Define an Agent

An AI agent is defined by four capabilities that a plain LLM call does not have:

**1. Tool Use**
The agent can call external functions — search a database, invoke an API, run a calculation, read a file. The LLM decides when and how to use each tool based on the question it is trying to answer.

**2. Memory**
The agent maintains state across steps. This can be short-term (what happened in this conversation) or long-term (facts stored in a vector database or knowledge graph that persist across sessions).

**3. Planning**
The agent can decompose a complex goal into sub-tasks, execute them in sequence or in parallel, and adapt the plan when intermediate results are unexpected.

**4. Multi-Agent Collaboration**
Complex tasks can be delegated. A supervisor agent breaks work into pieces and assigns each piece to a specialist agent — one for database queries, one for calculations, one for document retrieval. The supervisor collects results and synthesizes a final answer.

The clearest test of whether a system is genuinely agentic is this: does it demonstrate real decision-making, or is it following a static script? A workflow that always retrieves three documents, always passes them to the same prompt, and always returns the model's first response is not an agent — it is a deterministic pipeline with an LLM somewhere in the middle. An agent, by contrast, decides at runtime, based on what it sees, whether to retrieve more, whether to ask a clarifying question, or whether to stop and admit it does not know.

## 1.3 The Spectrum: From Pipeline to Agent

Enterprise AI systems do not fall neatly into "agent" or "not agent" — they sit on a spectrum. Understanding where your system lives helps you make deliberate architecture choices.

| System Type | Adaptability | Explainability | Typical Failure Mode |
|---|---|---|---|
| Deterministic pipeline | None — fixed logic | High | Hard error on unexpected input |
| Deterministic LLM workflow | Low — fixed structure, flexible model | High | Wrong but consistent |
| RAG system | Medium — retrieval adapts to query | High | Plausible but stale |
| **Agentic RAG (this book)** | **Medium-high — agent picks strategy at runtime** | **High** | **Honest "I don't know"** |
| Autonomous agent | High | Lower | Confidently off-task |

The system we build in this book sits deliberately in the middle of this spectrum. It is more than a fixed RAG pipeline — it makes runtime decisions about which retrieval strategy to use and how to combine the results — but it operates within a bounded domain rather than pursuing open-ended goals. For regulated enterprise work, the middle of the spectrum is where trust, cost, and capability balance.

## 1.4 Why This Matters for SAP Developers

SAP developers work in an ecosystem that is rich with structured data, complex business processes, and decades of accumulated knowledge locked in documents, systems, and workflows.

Consider what an agentic system can do in an SAP context:

- A logistics manager asks: *"Which of our open deliveries are at risk of missing the SLA, and what should we do about them?"* — The agent queries SAP S/4HANA OData APIs, retrieves delivery statuses, checks route data, reasons about delays, and proposes actions.

- A procurement analyst asks: *"Summarise the hazard information for all chemicals we ordered last quarter."* — The agent retrieves material safety data sheets, searches a knowledge graph for GHS classifications, cross-references a vector store of regulatory documents, and synthesises a compliance summary.

- A developer asks: *"What CAP annotations do I need to add to expose this entity as a Fiori list report?"* — The agent searches internal documentation, reads the CDS schema, and generates the exact annotations needed.

None of these tasks can be answered by a single database query or a single LLM prompt. They require reasoning, retrieval, and action — the three pillars of agentic AI.

### SAP's Strategic Direction: The Autonomous Enterprise

The timing of this book is not accidental. SAP has placed agentic AI at the centre of its entire product strategy.

At **SAP Sapphire 2026 in Orlando**, CEO **Christian Klein** unveiled the company's most significant AI announcement to date: a unified vision called the **Autonomous Enterprise** — a model where humans and AI collaborate continuously to execute, adapt, and optimise critical business processes. In Klein's own words:

> *"For the mission-critical processes of our customers, 'almost right' just isn't good enough. By uniting SAP Business AI Platform with SAP Autonomous Suite, we anchor AI agents in the business processes, data and governance so they can deliver accurate, compliant and secure outcomes, unlocking new sources of revenue and meaningful cost savings."*

The scale of SAP's AI buildout is notable:

| Milestone | Detail |
|-----------|--------|
| **50+ Joule Assistants** | Domain-specific AI assistants across Finance, Supply Chain, Procurement, HR, and Customer Experience |
| **200+ specialised agents** | Available for orchestration of precise business tasks across the SAP portfolio |
| **7 Industry AI solutions** | Vertical-specific autonomous solutions through the Industry AI initiative |
| **€100 million partner fund** | Launched to accelerate partner deployments of AI assistants and agents |
| **SAP Autonomous Suite** | A new product suite embedding agents directly into S/4HANA, Ariba, SuccessFactors, and more |

SAP also introduced **Joule Studio** — a no-code and pro-code environment for building custom agents on BTP — and **Joule Work**, a conversational interface that gives every business user access to the agent layer. These are precisely the tools this book's architecture is designed to extend.

### SAP's AI Partnerships and Infrastructure Investments

SAP is not building its AI strategy alone. The company announced a broad coalition of AI partnerships at Sapphire 2026, each serving a distinct role in the stack:

| Partner | Role |
|---------|------|
| **NVIDIA** | Provides OpenShell — the trusted, secure runtime environment for Joule Studio's agent execution |
| **Anthropic** | Foundation model partnership for Claude integration within SAP Business AI Platform |
| **Google Cloud** | Strategic AI infrastructure and Gemini model integration |
| **Microsoft** | Copilot integration and Azure AI services |
| **Mistral AI & Cohere** | European AI model options within the platform |
| **Palantir** | Enterprise data and AI operations |

SAP also announced acquisitions that signal the depth of its AI commitment. In May 2026, SAP announced plans to acquire **Prior Labs** — a frontier AI research lab based in Europe — with the explicit goal of establishing a "globally leading frontier AI lab" within the company. This follows the acquisition of **Reltio**, a master data management platform. Together, these moves signal that SAP intends to control the AI stack from the data layer through the model layer to the application layer.

### What This Means for You as a Developer

You are not building a side project. You are building on the platform and with the patterns that SAP itself is standardising for the next decade of enterprise software.

The architecture in this book — agents orchestrated with LangGraph, vector search and knowledge graphs on HANA Cloud, CAP Node.js as the API layer, exposed through Joule — maps directly to SAP's publicly stated direction. The skills you build here translate immediately to the Joule Studio agent development environment, to the SAP Business AI Platform, and to the autonomous enterprise patterns that SAP's largest customers are now adopting.

The 200+ agents SAP announced at Sapphire 2026 were not built by SAP alone. Partners, customers, and developers on BTP built them. This book shows you how to be one of those builders.

## 1.5 What We Build in This Book

This book builds a single, coherent, production-grade system called the **Hybrid RAG Agent**. It runs on SAP BTP (free trial) and uses Google Vertex AI for LLM and embedding capabilities.

The system answers questions about documents by combining two retrieval strategies in parallel:

**Vector Search** finds semantically similar content. When you ask *"What precautions are needed when handling acetone?"*, vector search finds all document chunks that are semantically close to that question — even if they do not use the exact same words.

**Knowledge Graph Search** finds structured facts. When you ask *"What is the GHS hazard code for acetone?"*, the knowledge graph returns a precise, structured answer via a SPARQL query — no ambiguity, no hallucination.

This hybrid approach exists because neither retrieval strategy alone is sufficient. Vector search is forgiving and handles narrative prose beautifully, but it wobbles on precise symbolic facts — asked for the GHS code for acetone, it might return the right paragraph at 0.65 cosine similarity sandwiched between unrelated chunks. Knowledge graphs answer symbolic queries precisely, but they cannot handle narrative questions that have no single structured answer. Run both in parallel, synthesise when both return, defer to whichever returns when only one does, and admit ignorance when neither does. That is the architecture we build.

The running example throughout the book is a domain-specific agent for **Material Safety Data Sheets (MSDS)** — the regulatory documents that govern how chemical substances are handled, stored, transported, and disposed of. MSDS documents are an ideal example for hybrid RAG because they contain both kinds of content in equal measure: dense narrative prose on one page (first-aid procedures, ventilation requirements) and precise structured data on the next (GHS hazard codes, exposure limits, flash points). A real user — say, a safety officer on a shop floor — asks questions about both, often in the same sentence.

A LangGraph orchestrator runs both searches in parallel, merges the results, and synthesises a final answer using Gemini 2.5 Flash. The system is exposed via a CAP Node.js OData V4 API with a Fiori Elements UI, and optionally extended to Joule A2A for enterprise SAP copilot integration.

![Agentic Hybrid RAG System Architecture](docs/screenshots/diagrams/02-agentic-rag-overview.png)

*Figure 1.1 — The Hybrid RAG Agent: user questions enter a FastAPI backend, which fans out to a Vector Chain (HANA REAL_VECTOR + cosine search) and a KG Chain (HANA SPARQL/RDF) running in parallel. Both results feed into Gemini 2.5 Flash for synthesis into a final cited answer.*

By the time you finish this book, you will have built a fully working system that:

- Ingests PDF documents and builds both a vector store and a knowledge graph automatically
- Answers questions using dual-retrieval hybrid RAG running locally
- Orchestrates multi-step reasoning with LangGraph
- Connects to SAP HANA Cloud (BTP trial) for vector and graph storage
- Calls Google Vertex AI for embeddings and LLM inference
- Exposes everything via CAP OData V4 with a Fiori Elements UI running locally

The architecture, the patterns, and the engineering choices we make along the way generalise far beyond MSDS. Substitute legal contracts and you have the skeleton of a legal agent. Substitute clinical guidelines and you have something close to a medical AI assistant. Substitute equipment maintenance manuals and you have a field-service agent. The domain changes. The pattern does not.

---

## 1.6 Scope of This Book

Before going further, it is important to be explicit about what this book covers and what it deliberately leaves out.

### What This Book Covers

| Topic | Coverage |
|-------|----------|
| Agentic AI concepts — tool use, memory, planning, multi-agent | Full coverage, Ch 1 |
| SAP BTP trial setup — HANA Cloud, CF space, Destination Service | Full coverage, Ch 2 |
| Vector search on HANA Cloud (REAL_VECTOR) | Full coverage, Ch 3 |
| Knowledge graphs on HANA Cloud (SPARQL/RDF) | Full coverage, Ch 4 |
| PDF ingestion pipeline — dual-threaded KG + vector | Full coverage, Ch 5 |
| LangGraph — state, nodes, edges, conditional routing | Full coverage, Ch 6 |
| Hybrid RAG agent — parallel chains, merge, orchestrator | Full coverage, Ch 7 |
| Multi-agent supervisor pattern — specialist agents | Full coverage, Ch 8 |
| CAP Node.js OData V4 service + Fiori Elements UI | Full coverage, Ch 9 |
| Deploying to SAP BTP Cloud Foundry | Full coverage, Ch 10 |
| Joule A2A integration | Appendix D (enterprise only) |
| SAP AI Core as LLM alternative | Appendix E (enterprise only) |

### What This Book Does NOT Cover

**Production-grade hardening.** This book teaches the architecture and implementation patterns. It does not cover rate limiting, multi-tenant isolation, secrets rotation, disaster recovery, or SLA monitoring.

**Fine-tuning or training models.** All LLM usage in this book is inference-only — calling hosted models via API.

**Multi-document cross-referencing.** The hybrid RAG agent answers questions about one MSDS document at a time. Cross-document reasoning is a natural extension but is not covered here.

**Streaming responses.** The agent returns complete answers synchronously.

**CI/CD pipelines.** Deployment in Chapter 10 uses manual `cf push` and `mbt build && cf deploy` commands.

**Joule and SAP AI Core on free trial.** Both require enterprise SAP subscriptions. They are covered in Appendices D and E specifically so readers with enterprise access can follow along, while the main chapters remain accessible to anyone on the free trial.

### Local Development is the Primary Mode

Most chapters in this book develop and test everything on your **local machine**, using:

- `uvicorn main:app --reload` for the FastAPI agent service
- `cds serve` for the CAP Node.js service
- Your local HANA Cloud trial instance (which is cloud-hosted but accessed from your laptop)
- The Vertex AI API called directly from your local Python environment

Chapter 10 then shows you how to deploy this same code — unchanged — to BTP Cloud Foundry.

> **Note:** You do not need to complete Chapter 10 to have a working system. Chapters 1–9 produce a fully functional Hybrid RAG Agent running locally against your BTP HANA Cloud trial. Chapter 10 is the production deployment step.

---

## 1.7 The Platform Choice: SAP BTP + Google Vertex AI

A recurring question in enterprise AI projects is: which platform? This book makes a deliberate, practical choice.

**SAP BTP** is the data and integration platform. It provides:
- SAP HANA Cloud — the only database that combines vector search and SPARQL knowledge graph storage in a single managed service
- Cloud Foundry runtime — free for developers, the same runtime used in production
- CAP Node.js — the standard for building SAP-native OData APIs
- Destination Service — secure, centralised credential management for external APIs

**Google Vertex AI** is the AI inference layer. It provides:
- Gemini 2.5 Flash — one of the best price-performance LLMs available today
- text-embedding-004 — state-of-the-art embeddings for semantic search
- $300 free trial credit — enough to build and test everything in this book at zero cost

SAP AI Core is deliberately excluded from the main examples. It is a viable alternative for organisations that require all components on BTP, but it is a paid service not available on the free trial. The architecture is designed so that swapping Vertex AI for AI Core requires changing only the LLM client — nothing else.

## 1.8 What You Need to Follow Along

To build everything in this book you need:

| Requirement | Where to Get It | Cost |
|-------------|----------------|------|
| SAP BTP Trial account | account.hanatrial.ondemand.com | Free |
| SAP HANA Cloud instance | BTP Trial cockpit | Free (30 days) |
| GCP account | cloud.google.com/free | Free ($300 credit) |
| Vertex AI API enabled | GCP Console | Free (within credit) |
| Python 3.11+ | python.org | Free |
| Node.js 20+ | nodejs.org | Free |
| CF CLI | CF documentation | Free |
| CDS CLI (`@sap/cds`) | npm | Free |
| VS Code | code.visualstudio.com | Free |

Chapter 2 walks through every setup step with screenshots. If you already have a BTP trial and a GCP account, Chapter 2 will take about 30 minutes.

## 1.9 Summary

- Agentic AI extends LLMs with tool use, memory, planning, and multi-agent collaboration — transforming passive completion into active reasoning
- The spectrum runs from deterministic pipelines through RAG to fully autonomous agents; this book builds in the middle, at "Agentic RAG"
- SAP developers have a unique opportunity: rich enterprise data, complex processes, and a platform (BTP) purpose-built for hybrid AI architectures
- SAP itself is betting on domain-specific agents: 200+ specialist agents announced at Sapphire 2026, the Autonomous Enterprise vision, and the Joule Studio development environment
- Hybrid retrieval is the right engine for domain-specific enterprise agents — vector search handles narrative questions, knowledge graphs handle precise symbolic facts; neither alone is sufficient
- This book builds a Hybrid RAG Agent: vector search + knowledge graph + LangGraph orchestration on SAP BTP, demonstrated through an MSDS safety data sheet assistant
- The full stack is free to build and test using BTP trial + GCP free credit

In Chapter 2, we set up the platform — BTP trial, HANA Cloud, GCP project, and Vertex AI credentials — so you have a working environment before we write a single line of code.
