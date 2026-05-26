# Agentic Hybrid RAG on SAP BTP

**A Hands-On Guide with LangGraph, HANA Cloud, and Google Vertex AI**
Author: Sriram Rokkam

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

The book chapters live in `docs/chapters/`. Every source file has a
`Book reference:` line in its docstring. The full chapter → file → function
map is at **[docs/CODE_MAP.md](docs/CODE_MAP.md)**.

---

## Get the Code

```bash
git clone https://github.com/sriramrokkam/agentic-hybrid-rag-on-sap-btp.git
cd agentic-hybrid-rag-on-sap-btp
```

> **Note:** Replace the URL above with your actual GitHub remote once you push
> this repo. To add the remote now:
> ```bash
> git remote add origin https://github.com/<your-username>/agentic-hybrid-rag-on-sap-btp.git
> git push -u origin main
> ```

---

## Architecture

```
User Question (Fiori UI / curl)
        │
        ▼
FastAPI + LangGraph Orchestrator   (agents/main.py)
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
           CAP OData V4 (cap-srv/)
           Fiori Elements UI
```

---

## Prerequisites

Install these before you begin.

| Tool | Where to get it | Required for |
|---|---|---|
| Python 3.11+ | [python.org](https://python.org) | Agent service |
| Node.js 20+ | [nodejs.org](https://nodejs.org) | CAP frontend |
| SAP BTP Trial account | [account.hanatrial.ondemand.com](https://account.hanatrial.ondemand.com) | HANA Cloud |
| SAP HANA Cloud instance | BTP Trial Cockpit → Service Marketplace | Database |
| GCP account | [cloud.google.com/free](https://cloud.google.com/free) | Vertex AI ($300 credit) |
| CF CLI | [docs.cloudfoundry.org](https://docs.cloudfoundry.org/cf-cli/install-go-cli.html) | BTP deployment |
| CDS CLI | `npm install -g @sap/cds-dk` | CAP development |

> **Platform setup details** — see `docs/chapters/chapter-03-platform-setup.md`
> for step-by-step walkthrough with screenshots.

---

## Project Structure

```
agentic-hybrid-rag-on-sap-btp/
│
├── agents/                         Python FastAPI + LangGraph service
│   ├── agents/
│   │   ├── state.py                LangGraph TypedDict state definitions
│   │   ├── orchestrator.py         Parallel chain dispatch + merge      [Ch 8]
│   │   ├── vector_chain.py         Embed → HANA cosine search → summarize [Ch 8]
│   │   ├── kg_chain.py             SPARQL generation → HANA → summarize  [Ch 8]
│   │   ├── supervisor.py           Multi-agent supervisor pattern        [Ch 9]
│   │   └── simple_qa_agent.py      Basic LangGraph agent (intro)         [Ch 7]
│   ├── srv/
│   │   ├── hdb_srv.py              HANA Cloud connection (thread-local)  [Ch 4]
│   │   ├── vertex_srv.py           Vertex AI LLM + embeddings            [Ch 4]
│   │   ├── vector_srv.py           Vector store CRUD                     [Ch 4]
│   │   ├── kg_srv.py               Knowledge graph CRUD + ontology load  [Ch 5]
│   │   └── doc_srv.py              PDF ingestion dual pipeline           [Ch 6]
│   ├── tools/tools.py              LangGraph tool definitions            [Ch 7]
│   ├── tests/
│   │   ├── test_vector.py          Vector store integration tests        [Ch 4]
│   │   └── test_kg.py              Knowledge graph integration tests     [Ch 5]
│   ├── main.py                     FastAPI entrypoint (all endpoints)    [Ch 6,8,9]
│   ├── manifest.yml                BTP Cloud Foundry deploy config
│   ├── requirements.txt            Python dependencies
│   └── .env.example                Environment variable template ← copy to .env
│
├── cap-srv/                        CAP Node.js OData V4 + Fiori UI
│   ├── db/schema.cds               Documents entity, dual-status model   [Ch 10]
│   ├── srv/service.cds             OData V4 service + actions            [Ch 10]
│   ├── srv/service.js              Action handlers (proxy to FastAPI)    [Ch 10]
│   ├── package.json
│   ├── mta.yaml                    BTP MTA deployment descriptor
│   └── .env.example                CAP env template ← copy to .env
│
├── joule/
│   └── README.md                   Joule A2A — Appendix D (enterprise only)
│
├── docs/
│   ├── CODE_MAP.md                 Chapter → file → function reference
│   ├── chapters/                   All book chapters (Markdown)
│   └── screenshots/                BTP, HANA, GCP setup screenshots
│
├── MSDS_Ontology.ttl               OWL ontology for KG triple extraction
└── .gitignore
```

---

## Local Development — Step by Step

Follow these steps in order. The agent service must be running before you
start the CAP frontend.

---

### Step 1 — Clone the repository

```bash
git clone https://github.com/sriramrokkam/agentic-hybrid-rag-on-sap-btp.git
cd agentic-hybrid-rag-on-sap-btp
```

---

### Step 2 — Set up the Python agent service

```bash
cd agents
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

---

### Step 3 — Configure environment variables

```bash
cp .env.example .env
```

Open `agents/.env` in your editor and fill in every value:

```dotenv
# ── SAP HANA Cloud ────────────────────────────────────────────────────────────
# Find these in BTP Cockpit → HANA Cloud → Instances → your instance → Actions → Copy SQL Endpoint
HANA_HOST=abc123.hanacloud.ondemand.com
HANA_PORT=443
HANA_USER=DBADMIN
HANA_PASSWORD=YourHanaPassword

# ── Google Cloud / Vertex AI ──────────────────────────────────────────────────
# GCP_PROJECT_ID: your GCP project ID (not the name) — found in GCP Console top bar
GCP_PROJECT_ID=my-project-123456
# GCP_LOCATION: region where you enabled Vertex AI
GCP_LOCATION=us-central1
# GOOGLE_APPLICATION_CREDENTIALS: absolute path to the service account JSON key
# you downloaded in Chapter 3. Keep this file OUTSIDE the repo directory.
GOOGLE_APPLICATION_CREDENTIALS=/Users/yourname/keys/gcp-sa-key.json

# ── LangSmith tracing (optional) ─────────────────────────────────────────────
# Sign up free at smith.langchain.com to trace LangGraph runs
LANGCHAIN_TRACING_V2=false
LANGCHAIN_API_KEY=
```

> **Where to find each value** — `docs/chapters/chapter-03-platform-setup.md`
> has annotated screenshots for both HANA Cloud and GCP credential setup.

> **Security:** `agents/.env` is in `.gitignore`. Never commit it.
> Never put your GCP service account JSON key inside this repo directory.

---

### Step 4 — Start the agent service

```bash
# still inside agents/ with .venv active
uvicorn main:app --reload --port 8000
```

Verify it is running:

```bash
curl http://localhost:8000/health
# expected: {"status":"ok"}
```

The interactive API docs are at **http://localhost:8000/docs** — you can test
every endpoint from the browser there.

---

### Step 5 — Load the MSDS ontology into HANA (first time only)

This loads `MSDS_Ontology.ttl` into HANA so the knowledge graph pipeline has
the ontology constraints it needs. Run once after provisioning a fresh HANA
instance.

```bash
curl -X POST http://localhost:8000/admin/load-ontology
# expected: {"status":"ok","triplesLoaded":<n>}
```

---

### Step 6 — Set up the CAP frontend

Open a **new terminal** (keep the agent service running in the first one).

```bash
cd cap-srv
cp .env.example .env          # AGENT_URL=http://localhost:8000 (default is fine)
npm install
cds serve
# OData V4 service: http://localhost:4004
# Fiori Elements UI: http://localhost:4004/$fiori-preview (once app/ is built)
```

---

### Step 7 — Upload a test document and run a query

With both services running, try the full flow:

**Upload an MSDS PDF:**

```bash
curl -X POST http://localhost:8000/process-upload \
  -F "file=@/path/to/acetone-msds.pdf" \
  -F "materialNumber=ACETONE-001" \
  -F "materialName=Acetone"
# {"status":"processing","materialNumber":"ACETONE-001"}
```

**Poll until ingestion completes:**

```bash
curl http://localhost:8000/status/ACETONE-001
# {"kgStatus":"DONE","vectorStatus":"DONE","complete":true, ...}
```

**Ask a question (parallel hybrid RAG):**

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What are the GHS hazard codes for acetone?",
    "material_number": "ACETONE-001"
  }'
```

**Ask a multi-domain question (supervisor):**

```bash
curl -X POST http://localhost:8000/query-advanced \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What are the hazard codes, exposure limits, and PPE requirements for acetone?",
    "material_number": "ACETONE-001",
    "use_supervisor": true
  }'
```

**Delete a document:**

```bash
curl -X DELETE http://localhost:8000/delete/ACETONE-001
# {"materialNumber":"ACETONE-001","vectorsDeleted":12,"kgDeleted":true}
```

---

### Step 8 — Run the integration tests

Tests require a live HANA connection and valid Vertex AI credentials (`.env` must be filled in).

```bash
cd agents
source .venv/bin/activate
pytest tests/ -v
```

---

## All API Endpoints

| Method | Path | Description | Chapter |
|---|---|---|---|
| `GET` | `/health` | Health check | — |
| `POST` | `/process-upload` | Upload PDF → dual ingestion (fire-and-forget) | Ch 6 |
| `GET` | `/status/{material_number}` | Poll ingestion status | Ch 6 |
| `DELETE` | `/delete/{material_number}` | Cascade-delete from vector + KG + DB | Ch 6 |
| `POST` | `/admin/load-ontology` | Load `MSDS_Ontology.ttl` into HANA (run once) | Ch 5 |
| `POST` | `/query` | Parallel hybrid RAG query | Ch 8 |
| `POST` | `/query-advanced` | Multi-agent supervisor query | Ch 9 |

Interactive docs at `http://localhost:8000/docs` when the service is running.

---

## Environment Variables Reference

### `agents/.env`

| Variable | Required | Where to find it |
|---|---|---|
| `HANA_HOST` | Yes | BTP Cockpit → HANA Cloud → SQL endpoint hostname |
| `HANA_PORT` | Yes | Always `443` for HANA Cloud |
| `HANA_USER` | Yes | Your HANA DB user (default: `DBADMIN`) |
| `HANA_PASSWORD` | Yes | The password you set when creating the HANA instance |
| `GCP_PROJECT_ID` | Yes | GCP Console top bar → project selector |
| `GCP_LOCATION` | Yes | Region where you enabled Vertex AI (e.g. `us-central1`) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Yes | Absolute path to service account JSON key (Ch 3) |
| `LANGCHAIN_TRACING_V2` | No | `true` to enable LangSmith tracing |
| `LANGCHAIN_API_KEY` | No | LangSmith API key from smith.langchain.com |

### `cap-srv/.env`

| Variable | Required | Description |
|---|---|---|
| `AGENT_URL` | Yes | URL of the Python agent service. Local: `http://localhost:8000` |

---

## Deploying to SAP BTP Cloud Foundry

> See `docs/chapters/chapter-11-btp-deployment.md` for the full walkthrough.

### Deploy the Python agent service

```bash
cd agents
cf login -a https://api.cf.us10.hana.ondemand.com   # adjust region if needed
# Set credentials as CF env vars — never in manifest.yml:
cf set-env hybrid-rag-agent HANA_HOST your-host
cf set-env hybrid-rag-agent HANA_PASSWORD your-password
cf set-env hybrid-rag-agent GCP_PROJECT_ID your-project
# ... set all other env vars the same way
cf push
```

### Deploy CAP + HANA via MTA

```bash
cd cap-srv
npm install -g mbt
mbt build
cf deploy mta_archives/*.mtar
```

After deployment, run the ontology loader once against the production URL:

```bash
curl -X POST https://hybrid-rag-agent.<your-cf-domain>/admin/load-ontology
```

---

## Book ↔ Code Cross-Reference

See **[docs/CODE_MAP.md](docs/CODE_MAP.md)** for the full chapter → file →
function table. Every Python source file also has a `Book reference:` line
in its docstring.

Book chapters are in `docs/chapters/`:

| File | Chapter |
|---|---|
| `chapter-01-agentic-era.md` | Ch 1 — Welcome to the Agentic Era |
| `chapter-02-why-sap-developers.md` | Ch 2 — Why SAP Developers Should Care |
| `chapter-03-platform-setup.md` | Ch 3 — Platform Setup (BTP + Vertex AI) |
| `chapter-04-vector-search-hana.md` | Ch 4 — Vector Search on HANA Cloud |
| `chapter-05-knowledge-graph-hana.md` | Ch 5 — Knowledge Graphs on HANA Cloud |
| `chapter-06-pdf-ingestion.md` | Ch 6 — The PDF Ingestion Pipeline |
| `chapter-07-langgraph-fundamentals.md` | Ch 7 — LangGraph Fundamentals |
| `chapter-08-hybrid-rag-agent.md` | Ch 8 — The Parallel Hybrid RAG Agent |
| `chapter-09-multi-agent-supervisor.md` | Ch 9 — The Multi-Agent Supervisor |

---

## License

Code: MIT License
Book content: Copyright © 2026 Sriram Rokkam. All rights reserved.
