# Agentic Hybrid RAG on SAP BTP

**A Hands-On Guide with LangGraph, HANA Cloud, and Google Vertex AI**
Author: Sriram Rokkam

---

## What This Repo Is

Companion code for the book *Agentic Hybrid RAG on SAP BTP*. It builds a production-ready AI agent that answers questions about Material Safety Data Sheets (MSDS/SDS) by combining:

- **Vector search** — SAP HANA Cloud `REAL_VECTOR` with Vertex AI embeddings
- **Knowledge graph search** — SAP HANA Cloud SPARQL/RDF with LLM-generated queries
- **Parallel orchestration** — LangGraph with `ThreadPoolExecutor`, both chains run simultaneously
- **SAP-native API** — CAP Node.js OData V4 + Fiori Elements UI

Everything runs on **SAP BTP free trial + GCP $300 free credit**.

---

## Architecture

```
User Question (Fiori UI)
        │
        ▼
LangGraph Orchestrator (BTP Cloud Foundry)
  ┌─────────────────────┬─────────────────────────┐
  │  Vector Chain       │      KG Chain            │
  │  text-embedding-004 │ Gemini → SPARQL          │
  │  HANA REAL_VECTOR   │ HANA SPARQL_EXECUTE      │
  │  cosine search      │ Gemini → summarize        │
  └──────────┬──────────┴────────────┬─────────────┘
             │   (parallel)          │
             └──────────┬────────────┘
                        ▼
               Gemini 2.5 Flash
               Answer Synthesis
```

---

## Prerequisites

| Requirement | Where | Cost |
|---|---|---|
| Python 3.11+ | python.org | Free |
| Node.js 20+ | nodejs.org | Free |
| SAP BTP Trial account | account.hanatrial.ondemand.com | Free |
| SAP HANA Cloud instance | BTP Trial Cockpit | Free |
| GCP account | cloud.google.com/free | Free ($300 credit) |
| CF CLI | docs.cloudfoundry.org | Free |
| CDS CLI | `npm i -g @sap/cds-dk` | Free |

---

## Project Structure

```
agentic-hybrid-rag-on-sap-btp/
├── agents/
│   ├── agents/
│   │   ├── orchestrator.py     Parallel chain dispatch + merge
│   │   ├── kg_chain.py         SPARQL generation → HANA → summarize
│   │   ├── vector_chain.py     Embed → HANA cosine search → summarize
│   │   ├── supervisor.py       Multi-agent supervisor (Ch 9)
│   │   └── state.py            LangGraph state definitions
│   ├── srv/
│   │   ├── hdb_srv.py          HANA Cloud connection (thread-local)
│   │   ├── vertex_srv.py       Vertex AI LLM + embedding client
│   │   ├── doc_srv.py          PDF ingestion pipeline
│   │   ├── kg_srv.py           Knowledge graph CRUD
│   │   └── vector_srv.py       Vector store CRUD
│   ├── tools/tools.py          LangGraph tool definitions
│   ├── tests/                  Unit + integration tests
│   ├── main.py                 FastAPI entrypoint
│   ├── manifest.yml            BTP CF deployment descriptor
│   ├── requirements.txt
│   └── .env.example
├── cap-srv/
│   ├── db/schema.cds           Data model (Documents entity)
│   ├── srv/service.cds         OData V4 service definition
│   ├── srv/service.js          Action handlers (proxy to FastAPI)
│   ├── package.json
│   └── mta.yaml                MTA deployment descriptor
├── joule/                      Joule A2A (Appendix D — enterprise only)
├── MSDS_Ontology.ttl           OWL ontology for KG extraction
└── .gitignore
```

---

## Book ↔ Code Cross-Reference

Every source file has a `Book reference:` line in its docstring pointing to
the chapter that explains it. For the full map see **[docs/CODE_MAP.md](docs/CODE_MAP.md)**.

---

## Quick Start — Local Development

### 1. Clone and configure

```bash
git clone https://github.com/sriramrokkam/agentic-hybrid-rag-on-sap-btp
cd agentic-hybrid-rag-on-sap-btp
```

### 2. Agent service (Python FastAPI)

```bash
cd agents
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your credentials:

```
HANA_HOST=<your-hana-instance>.hanacloud.ondemand.com
HANA_PORT=443
HANA_USER=DBADMIN
HANA_PASSWORD=<your-password>

GCP_PROJECT_ID=<your-gcp-project>
GCP_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=/path/to/gcp-sa-key.json
```

Start the agent service:

```bash
uvicorn main:app --reload --port 8000
```

Verify it works:

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

### 3. CAP frontend (Node.js)

Open a new terminal:

```bash
cd cap-srv
npm install
cds serve
# OData service running at http://localhost:4004
```

### 4. Run tests

```bash
cd agents
pytest tests/ -v
```

---

## Key Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/upload` | Upload an MSDS PDF for dual ingestion |
| `GET` | `/status/{material_number}` | Poll ingestion status |
| `POST` | `/query` | Hybrid RAG query (parallel chains) |
| `POST` | `/query-advanced` | Multi-agent supervisor query |
| `DELETE` | `/document/{material_number}` | Delete document from both stores |
| `GET` | `/health` | Health check |

---

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `HANA_HOST` | Yes | HANA Cloud instance hostname |
| `HANA_PORT` | Yes | HANA port (443 for cloud) |
| `HANA_USER` | Yes | HANA database user |
| `HANA_PASSWORD` | Yes | HANA database password |
| `GCP_PROJECT_ID` | Yes | GCP project containing Vertex AI |
| `GCP_LOCATION` | Yes | GCP region (e.g. `us-central1`) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Yes | Path to service account JSON key |
| `LANGCHAIN_TRACING_V2` | No | Enable LangSmith tracing (`true`/`false`) |
| `LANGCHAIN_API_KEY` | No | LangSmith API key |

---

## Deploying to SAP BTP Cloud Foundry

### Deploy the agent service

```bash
cd agents
cf login -a https://api.cf.us10.hana.ondemand.com
cf push
```

### Deploy CAP + HANA

```bash
cd cap-srv
npm install -g mbt
mbt build
cf deploy mta_archives/*.mtar
```

> **Note:** Set all HANA and Vertex AI credentials as CF environment variables or BTP User-Provided Services before pushing — never commit credentials.

---

## License

Code: MIT License
Book content: Copyright © 2026 Sriram Rokkam. All rights reserved.
