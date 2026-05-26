# Agentic Hybrid RAG on SAP BTP

**A Hands-On Guide with LangGraph, HANA Cloud, and Google Vertex AI**
Author: Sriram Rokkam | First Edition, May 2026

GitHub: [https://github.com/sriramrokkam/Book-Agentic-Hybrid-RAG-on-BTP](https://github.com/sriramrokkam/Book-Agentic-Hybrid-RAG-on-BTP)

---

## What This Repo Is

Companion code for the book *Agentic Hybrid RAG on SAP BTP*. It builds a
production-ready AI agent that answers questions about Material Safety Data
Sheets (MSDS/SDS) by combining:

- **Vector search** — SAP HANA Cloud `REAL_VECTOR` with Vertex AI `text-embedding-004`
- **Knowledge graph** — SAP HANA Cloud SPARQL/RDF with Gemini-generated queries
- **Parallel orchestration** — LangGraph with `ThreadPoolExecutor`, both chains run simultaneously
- **SAP-native API** — CAP Node.js OData V4 + Fiori Elements UI

Everything runs on **SAP BTP free trial + GCP $300 free credit**.

The book chapters (Markdown) live in `docs/chapters/`. The compiled PDF is at
`Agentic-Hybrid-RAG-on-SAP-BTP.pdf`. Every source file has a `Book reference:`
line in its docstring. The full chapter → file → function map is at
**[docs/CODE_MAP.md](docs/CODE_MAP.md)**.

---

## Book Contents

| # | Chapter / Appendix | Pages |
|---|---|---|
| 00 | Front Matter — Preface, Prerequisites, Companion Repo | 8 |
| 01 | Welcome to the Agentic Era | 15 |
| 02 | What Is Agentic AI — And Why SAP Developers Should Care | 11 |
| 03 | Platform Setup — SAP BTP Trial + Google Vertex AI | 14 |
| 04 | Vector Search on SAP HANA Cloud | 23 |
| 05 | Knowledge Graphs on SAP HANA Cloud | 21 |
| 06 | The PDF Ingestion Pipeline | 17 |
| 07 | LangGraph Fundamentals | 11 |
| 08 | The Parallel Hybrid RAG Agent | 13 |
| 09 | The Multi-Agent Supervisor Pattern | 11 |
| 10 | CAP Node.js OData V4 — The SAP-Native API Layer + Fiori UI | 19 |
| 11 | Deploying to SAP BTP Cloud Foundry | 19 |
| A | Appendix A — SAP BTP Trial Setup: Step-by-Step | 12 |
| B | Appendix B — Google Cloud Setup: Vertex AI, Gemini, Service Accounts | 12 |
| C | Appendix C — Full Code Reference | 10 |
| D | Appendix D — Joule A2A Integration *(enterprise, requires S/4HANA Cloud PE)* | 18 |
| **Total** | | **~295 pages** |

---

## Architecture

```
User Question (Fiori UI / curl / Joule A2A)
        │
        ▼
FastAPI + LangGraph Orchestrator   (agents/main.py  :8000)
  ┌─────────────────────┬──────────────────────────┐
  │  Vector Chain       │      KG Chain             │
  │  text-embedding-004 │  Gemini → SPARQL query    │
  │  HANA REAL_VECTOR   │  HANA SPARQL_EXECUTE      │
  │  cosine search      │  Gemini → summarize       │
  └──────────┬──────────┴─────────────┬─────────────┘
             │   (parallel threads)   │
             └───────────┬────────────┘
                         ▼
                Gemini 2.5 Flash
                Answer Synthesis
                         │
                         ▼
           CAP OData V4 (cap-srv/  :4004)
           Fiori Elements UI
```

---

## Prerequisites

| Tool | Where to get it | Required for |
|---|---|---|
| Python 3.11+ | [python.org](https://python.org) | Agent service |
| Node.js 20+ | [nodejs.org](https://nodejs.org) | CAP frontend |
| SAP BTP Trial | [account.hanatrial.ondemand.com](https://account.hanatrial.ondemand.com) | HANA Cloud |
| SAP HANA Cloud instance | BTP Cockpit → Service Marketplace | Database |
| GCP account | [cloud.google.com/free](https://cloud.google.com/free) | Vertex AI ($300 credit) |
| CF CLI | [docs.cloudfoundry.org](https://docs.cloudfoundry.org/cf-cli/install-go-cli.html) | BTP deployment |
| CDS CLI | `npm install -g @sap/cds-dk` | CAP development |

> Full setup walkthrough with screenshots:
> - **Appendix A** (`docs/chapters/appendix-a-btp-setup.md`) — SAP BTP Trial
> - **Appendix B** (`docs/chapters/appendix-b-gcp-setup.md`) — Google Cloud / Vertex AI

---

## Project Structure

```
book-agentic-hybrid-rag-on-btp/
│
├── agents/                         Python FastAPI + LangGraph service
│   ├── agents/
│   │   ├── state.py                LangGraph TypedDict state definitions   [Ch 8,9]
│   │   ├── orchestrator.py         Parallel chain dispatch + merge         [Ch 8]
│   │   ├── vector_chain.py         Embed → HANA cosine search → summarize  [Ch 8]
│   │   ├── kg_chain.py             SPARQL generation → HANA → summarize    [Ch 8]
│   │   └── supervisor.py           Multi-agent supervisor pattern          [Ch 9]
│   ├── srv/
│   │   ├── hdb_srv.py              HANA Cloud connection (thread-local)    [Ch 4]
│   │   ├── vertex_srv.py           Vertex AI LLM + embeddings              [Ch 4]
│   │   ├── vector_srv.py           Vector store CRUD                       [Ch 4]
│   │   ├── kg_srv.py               Knowledge graph CRUD + ontology load    [Ch 5]
│   │   └── doc_srv.py              PDF ingestion dual pipeline             [Ch 6]
│   ├── tests/
│   │   ├── test_vector.py          Vector store integration tests          [Ch 4]
│   │   └── test_kg.py              Knowledge graph integration tests       [Ch 5]
│   ├── main.py                     FastAPI entrypoint (all endpoints)      [Ch 6,8,9]
│   ├── manifest.yml                BTP Cloud Foundry deploy config         [Ch 11]
│   ├── requirements.txt            Python dependencies
│   └── .env.example                Environment variable template
│
├── cap-srv/                        CAP Node.js OData V4 + Fiori UI
│   ├── db/schema.cds               Documents entity, dual-status model     [Ch 10]
│   ├── srv/service.cds             OData V4 service + actions              [Ch 10]
│   ├── srv/service.js              Action handlers (proxy to FastAPI)      [Ch 10]
│   ├── srv/annotations.cds         Fiori Elements UI annotations           [Ch 10]
│   ├── package.json
│   ├── mta.yaml                    BTP MTA deployment descriptor           [Ch 11]
│   └── .env.example                CAP env template
│
├── joule/
│   └── README.md                   Joule A2A — see Appendix D
│
├── docs/
│   ├── CODE_MAP.md                 Chapter → file → function reference
│   ├── chapters/                   All book chapters + appendices (Markdown)
│   └── screenshots/                BTP, HANA, GCP, architecture diagrams
│
├── MSDS_Ontology.ttl               OWL ontology for KG triple extraction   [Ch 5]
├── Agentic-Hybrid-RAG-on-SAP-BTP.pdf   Book PDF (295 pages)
├── book-header.tex                 LaTeX header for PDF generation
└── .gitignore
```

---

## Local Development — Step by Step

### Step 1 — Clone

```bash
git clone https://github.com/sriramrokkam/Book-Agentic-Hybrid-RAG-on-BTP.git
cd Book-Agentic-Hybrid-RAG-on-BTP
```

### Step 2 — Python agent service

```bash
cd agents
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

### Step 3 — Configure environment variables

```bash
cp .env.example .env
# Edit agents/.env — fill in every value below
```

```dotenv
# SAP HANA Cloud — BTP Cockpit → HANA Cloud → Actions → Copy SQL Endpoint
HANA_HOST=abc123.hanacloud.ondemand.com
HANA_PORT=443
HANA_USER=DBADMIN
HANA_PASSWORD=YourHanaPassword

# Google Cloud / Vertex AI — see Appendix B for where to find these
GOOGLE_API_KEY=your-gemini-api-key
GCP_PROJECT_ID=my-project-123456
GCP_LOCATION=us-central1

# LangSmith tracing (optional — sign up free at smith.langchain.com)
LANGCHAIN_TRACING_V2=false
LANGCHAIN_API_KEY=
```

> **Security:** `agents/.env` is in `.gitignore`. Never commit it.
> Never store your GCP service account JSON key inside this repo directory.

### Step 4 — Start the agent service

```bash
uvicorn main:app --reload --port 8000
```

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

Interactive API docs: **http://localhost:8000/docs**

### Step 5 — Load the MSDS ontology (first time only)

```bash
curl -X POST http://localhost:8000/admin/load-ontology
# {"status":"ok","triplesLoaded":<n>}
```

### Step 6 — Start the CAP frontend

New terminal:

```bash
cd cap-srv
cp .env.example .env     # AGENT_URL=http://localhost:8000
npm install
cds serve
# OData V4 at http://localhost:4004
```

### Step 7 — Upload a document and run a query

```bash
# Upload a PDF
curl -X POST http://localhost:8000/process-upload \
  -F "file=@/path/to/acetone-msds.pdf" \
  -F "materialNumber=ACETONE-001"

# Poll until done
curl http://localhost:8000/status/ACETONE-001

# Hybrid RAG query (parallel vector + KG)
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question":"What are the GHS hazard codes for acetone?","material_number":"ACETONE-001"}'

# Multi-agent supervisor query
curl -X POST http://localhost:8000/query-advanced \
  -H "Content-Type: application/json" \
  -d '{"question":"Hazard codes, exposure limits, and PPE for acetone?","material_number":"ACETONE-001"}'

# Delete a document
curl -X DELETE http://localhost:8000/delete/ACETONE-001
```

### Step 8 — Run integration tests

```bash
pytest tests/ -v
```

---

## All API Endpoints

| Method | Path | Description | Chapter |
|---|---|---|---|
| `GET` | `/health` | Health check | — |
| `POST` | `/process-upload` | Upload PDF → dual ingestion (fire-and-forget) | Ch 6 |
| `GET` | `/status/{material_number}` | Poll ingestion status | Ch 6 |
| `DELETE` | `/delete/{material_number}` | Cascade-delete vectors + KG + DB | Ch 6 |
| `POST` | `/admin/load-ontology` | Load `MSDS_Ontology.ttl` into HANA (once) | Ch 5 |
| `POST` | `/query` | Parallel hybrid RAG query | Ch 8 |
| `POST` | `/query-advanced` | Multi-agent supervisor query | Ch 9 |
| `POST` | `/a2a` | Joule A2A protocol endpoint | App D |

---

## Environment Variables Reference

### `agents/.env`

| Variable | Required | Where to find it |
|---|---|---|
| `HANA_HOST` | Yes | BTP Cockpit → HANA Cloud → SQL endpoint (hostname only) |
| `HANA_PORT` | Yes | Always `443` for HANA Cloud |
| `HANA_USER` | Yes | HANA DB user (default: `DBADMIN`) |
| `HANA_PASSWORD` | Yes | Password set when creating the HANA instance |
| `GOOGLE_API_KEY` | Yes* | GCP Console → APIs & Services → Credentials → API Key |
| `GCP_PROJECT_ID` | Yes | GCP Console top bar → project selector |
| `GCP_LOCATION` | Yes | Region where Vertex AI is enabled (e.g. `us-central1`) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Yes* | Absolute path to service account JSON key |
| `LANGCHAIN_TRACING_V2` | No | `true` to enable LangSmith tracing |
| `LANGCHAIN_API_KEY` | No | LangSmith API key |

*Use either `GOOGLE_API_KEY` (simpler, dev) or `GOOGLE_APPLICATION_CREDENTIALS` (BTP deployment).

### `cap-srv/.env`

| Variable | Required | Description |
|---|---|---|
| `AGENT_URL` | Yes | Python agent URL. Local: `http://localhost:8000` |

---

## Deploying to SAP BTP Cloud Foundry

> Full walkthrough: `docs/chapters/chapter-11-btp-deployment.md`

```bash
# 1. Push the Python agent
cd agents
cf login -a https://api.cf.us10.hana.ondemand.com
cf push --no-start
cf set-env hybrid-rag-agent HANA_HOST your-host
cf set-env hybrid-rag-agent HANA_PASSWORD your-password
cf set-env hybrid-rag-agent GOOGLE_API_KEY your-key
cf set-env hybrid-rag-agent GCP_PROJECT_ID your-project
cf start hybrid-rag-agent

# 2. Deploy CAP + HANA via MTA
cd ../cap-srv
npm install -g mbt
mbt build
cf deploy mta_archives/*.mtar

# 3. Load ontology against production URL
curl -X POST https://hybrid-rag-agent.<your-cf-domain>/admin/load-ontology
```

---

## Generate the PDF

Requires `pandoc`, `xelatex`, and the 72 Brand font (SAP brand font).

```bash
pandoc \
  docs/chapters/chapter-0{0,1,2,3,4,5,6,7,8,9}*.md \
  docs/chapters/chapter-1*.md \
  docs/chapters/appendix-*.md \
  -o Agentic-Hybrid-RAG-on-SAP-BTP.pdf \
  --pdf-engine=xelatex \
  --syntax-highlighting=tango \
  --toc \
  --include-in-header=book-header.tex \
  -V papersize=a4 -V fontsize=11pt \
  -M title="Agentic Hybrid RAG on SAP BTP" \
  -M author="Sriram Rokkam" \
  -M date="May 2026"
```

---

## Book ↔ Code Cross-Reference

See **[docs/CODE_MAP.md](docs/CODE_MAP.md)** for the full chapter → file → function table.

| File | Content |
|---|---|
| `chapter-01-agentic-era.md` | The Agentic Era |
| `chapter-02-why-sap-developers.md` | Why SAP Developers Should Care |
| `chapter-03-platform-setup.md` | Platform Setup (BTP + Vertex AI) |
| `chapter-04-vector-search-hana.md` | Vector Search on HANA Cloud |
| `chapter-05-knowledge-graph-hana.md` | Knowledge Graphs on HANA Cloud |
| `chapter-06-pdf-ingestion.md` | PDF Ingestion Pipeline |
| `chapter-07-langgraph-fundamentals.md` | LangGraph Fundamentals |
| `chapter-08-hybrid-rag-agent.md` | The Parallel Hybrid RAG Agent |
| `chapter-09-multi-agent-supervisor.md` | The Multi-Agent Supervisor |
| `chapter-10-cap-fiori-ui.md` | CAP OData V4 + Fiori Elements UI |
| `chapter-11-btp-deployment.md` | BTP Cloud Foundry Deployment |
| `appendix-a-btp-setup.md` | SAP BTP Trial Setup |
| `appendix-b-gcp-setup.md` | Google Cloud / Vertex AI Setup |
| `appendix-c-code-reference.md` | Full Code Reference |
| `appendix-d-joule-a2a.md` | Joule A2A Integration |

---

## License

Code: MIT License
Book content: Copyright © 2026 Sriram Rokkam. All rights reserved.
