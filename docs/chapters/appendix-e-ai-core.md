# Appendix E: SAP AI Core — Enterprise LLM Integration

---

> **Who this appendix is for.** This appendix is for readers who have access to an SAP AI Core enterprise subscription and want to use SAP-managed foundation models instead of Google Vertex AI. The agent architecture, LangGraph orchestration, and HANA Cloud retrieval are identical — only the model provider changes. If you are using Vertex AI (the default for this book), you can skip this appendix entirely.

---

## E.1 What Is SAP AI Core?

SAP AI Core is the enterprise AI deployment and orchestration platform on SAP BTP. It provisions and runs foundation models at scale, manages model lifecycle, handles token quotas and rate limiting per tenant, and provides the secure inference endpoint that Joule uses internally.

For this book's use case, AI Core provides two things:

| Capability | Detail |
|---|---|
| **Generative AI Hub** | A unified API layer over multiple LLM providers — OpenAI GPT-4o, Anthropic Claude, Google Gemini, Mistral, and SAP's own models |
| **Embeddings endpoint** | A managed embedding model endpoint compatible with the same interface as Vertex AI's `text-embedding-004` |

The LangChain integration library `generative-ai-hub-sdk` wraps both endpoints with a familiar interface, making the swap from Vertex AI straightforward.

---

## E.2 Prerequisites

Before starting this appendix, confirm you have:

- An SAP BTP subaccount with **SAP AI Core** service entitlement (Standard or Extended plan)
- An **AI Launchpad** subscription in the same subaccount
- A service key for the AI Core instance (downloaded from BTP Cockpit → Services → Instances)

> **Trial accounts cannot use SAP AI Core.** AI Core requires a paid BTP subscription. Contact your SAP account executive or BTP administrator if you are unsure whether your organisation has the entitlement.

---

## E.3 Activating a Model in AI Launchpad

AI Launchpad is the browser-based control plane for AI Core. You use it to activate (deploy) a foundation model before your application can call it.

### Step 1 — Open AI Launchpad

In the BTP Cockpit, go to **Services** → **Instances and Subscriptions** → click **AI Launchpad** to open it.

### Step 2 — Create a Resource Group

Resource groups isolate model deployments by use case or team.

Go to **ML Operations** → **Resource Groups** → **Create**.

| Field | Value |
|---|---|
| Resource Group ID | `agentic-rag` |
| Labels | `project=book` (optional) |

### Step 3 — Activate a Generative AI Hub Model

Go to **Generative AI Hub** → **Models** → find the model you want to deploy.

For this book the recommended replacements are:

| Vertex AI model | AI Core equivalent |
|---|---|
| `gemini-2.5-flash` | `gpt-4o` or `claude-3-5-sonnet` |
| `text-embedding-004` | `text-embedding-ada-002` or SAP's managed embedding model |

Click the model → **Deploy** → select your resource group `agentic-rag` → **Deploy**.

Deployment takes 2–5 minutes. The model status changes from **Pending** to **Running**. Note the **Deployment ID** — you will need it in your configuration.

> **Note:** You are not charged for deploying a model. Charges apply only to token consumption during inference calls.

### Step 4 — Get the Inference Endpoint

Click your running deployment → copy the **Inference URL**. It will look like:

```
https://api.ai.prod.eu-central-1.aws.ml.hana.ondemand.com/v2/inference/deployments/<deployment-id>
```

---

## E.4 Getting the AI Core Service Key

In BTP Cockpit → **Services** → **Instances** → click your AI Core instance → **Service Keys** → **Create Service Key**.

Download the JSON. It contains:

```json
{
  "clientid": "sb-...",
  "clientsecret": "...",
  "url": "https://<tenant>.authentication.eu10.hana.ondemand.com",
  "serviceurls": {
    "AI_API_URL": "https://api.ai.prod.eu-central-1.aws.ml.hana.ondemand.com"
  }
}
```

Add these to your `agents/.env`:

```bash
AICORE_CLIENT_ID=<clientid>
AICORE_CLIENT_SECRET=<clientsecret>
AICORE_AUTH_URL=<url>
AICORE_BASE_URL=<AI_API_URL>
AICORE_RESOURCE_GROUP=agentic-rag
AICORE_DEPLOYMENT_ID=<your-deployment-id>
```

---

## E.5 Installing the SDK

```bash
pip install "generative-ai-hub-sdk[all]"
```

Verify the installation:

```bash
python -c "from gen_ai_hub.proxy.langchain import init_llm; print('SDK ready')"
```

---

## E.6 Calling the Model Directly (Python)

Before integrating with the agent, verify the model works standalone:

```python
from gen_ai_hub.proxy.core.proxy_clients import get_proxy_client
from gen_ai_hub.proxy.langchain import init_llm, init_embedding_model

# Initialise the proxy client (reads from environment variables automatically)
proxy_client = get_proxy_client("gen-ai-hub")

# Test LLM call
llm = init_llm("gpt-4o", proxy_client=proxy_client, temperature=0.0)
response = llm.invoke("In one sentence, what is SAP HANA Cloud?")
print(response.content)

# Test embedding call
embedding_model = init_embedding_model(
    "text-embedding-ada-002",
    proxy_client=proxy_client
)
vectors = embedding_model.embed_documents(["tensile strength test ISO 6892-1"])
print(f"Embedding dimension: {len(vectors[0])}")
```

Expected output:

```
SAP HANA Cloud is a cloud-native database that combines in-memory processing,
multi-model data management, and AI capabilities in a single managed service.
Embedding dimension: 1536
```

> **Note:** `text-embedding-ada-002` produces 1536-dimensional vectors, compared to 768 for Vertex AI's `text-embedding-004`. If you switch embedding models on an existing HANA Cloud deployment, you must re-embed all documents — the vector dimensions must match the `REAL_VECTOR` column definition. Either recreate the table with `REAL_VECTOR(1536)` or keep Vertex AI embeddings and use AI Core only for the LLM tasks.

---

## E.7 Replacing Gemini in the Agent

The agent uses two Gemini calls: one for SPARQL generation (the KG chain) and one for answer synthesis (the merge node). Both use the `_get_llm()` lazy getter pattern — swapping providers requires changing only that function.

### Step 1 — Replace `_get_llm()` in `agents/agents/llm.py`

```python
# Before (Vertex AI / Gemini)
from langchain_google_genai import ChatGoogleGenerativeAI

def _get_llm():
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0.0,
        max_tokens=2048,
    )

# After (SAP AI Core)
from gen_ai_hub.proxy.langchain import init_llm
from gen_ai_hub.proxy.core.proxy_clients import get_proxy_client

_proxy_client = None

def _get_proxy_client():
    global _proxy_client
    if _proxy_client is None:
        _proxy_client = get_proxy_client("gen-ai-hub")
    return _proxy_client

def _get_llm():
    return init_llm(
        "gpt-4o",
        proxy_client=_get_proxy_client(),
        temperature=0.0,
        max_tokens=2048,
    )
```

### Step 2 — Replace the embedding call in `agents/agents/vector_srv.py`

```python
# Before (Vertex AI)
from langchain_google_genai import GoogleGenerativeAIEmbeddings

def _get_embedding_model():
    return GoogleGenerativeAIEmbeddings(model="models/text-embedding-004")

# After (SAP AI Core)
from gen_ai_hub.proxy.langchain import init_embedding_model
from agents.llm import _get_proxy_client

def _get_embedding_model():
    return init_embedding_model(
        "text-embedding-ada-002",
        proxy_client=_get_proxy_client()
    )
```

> **Important:** If you already have vectors stored in HANA Cloud using `text-embedding-004` (768 dimensions), switching to `text-embedding-ada-002` (1536 dimensions) requires re-ingesting all documents. The vector dimensions must match. To avoid re-ingestion, keep Vertex AI for embeddings and swap only the LLM to AI Core.

### Step 3 — Update `.env`

Comment out the Vertex AI variables and add the AI Core variables from Section E.4:

```bash
# Vertex AI (comment out if using AI Core for LLM)
# GOOGLE_CLOUD_PROJECT=...
# GCP_LOCATION=us-central1

# SAP AI Core
AICORE_CLIENT_ID=...
AICORE_CLIENT_SECRET=...
AICORE_AUTH_URL=...
AICORE_BASE_URL=...
AICORE_RESOURCE_GROUP=agentic-rag
AICORE_DEPLOYMENT_ID=...
```

### Step 4 — Test the swapped agent

```bash
cd agents
python -c "
from agents.llm import _get_llm
llm = _get_llm()
result = llm.invoke('What is a batch quality certificate in SAP QM?')
print(result.content[:200])
"
```

If the response prints correctly, the swap is complete. Run the full agent:

```bash
uvicorn main:app --reload
curl -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"What test method was used?","material_number":"BATCH-QC-MAT-001","history":[]}'
```

The response structure is identical — `answer`, `kg_facts`, `vector_chunks`, `sources`. No changes to the CAP service, Fiori UI, or LangGraph graph are required.

---

## E.8 BTP Destination for AI Core (CF Deployment)

For BTP Cloud Foundry deployment, store AI Core credentials in the Destination Service rather than as CF environment variables.

In BTP Cockpit → **Connectivity** → **Destinations** → **Create** → **From Scratch**:

| Field | Value |
|---|---|
| Name | `SAP-AI-Core` |
| Type | `HTTP` |
| URL | `<AI_API_URL>` from service key |
| Authentication | `OAuth2ClientCredentials` |
| Client ID | `clientid` from service key |
| Client Secret | `clientsecret` from service key |
| Token Service URL | `<url>/oauth/token` from service key |

Add additional property:

| Property | Value |
|---|---|
| `ai-resource-group` | `agentic-rag` |

In `main.py`, read the destination at startup using the BTP Destination Service SDK — the same pattern used for the Vertex AI destination in Chapter 2.

---

## E.9 Summary

| Step | What you did |
|---|---|
| Activated model in AI Launchpad | Deployed `gpt-4o` and `text-embedding-ada-002` to resource group `agentic-rag` |
| Installed SDK | `pip install generative-ai-hub-sdk[all]` |
| Replaced `_get_llm()` | Swapped `ChatGoogleGenerativeAI` for `init_llm("gpt-4o", ...)` |
| Replaced embedding model | Swapped `GoogleGenerativeAIEmbeddings` for `init_embedding_model(...)` |
| Updated `.env` | Added AI Core credentials, commented out Vertex AI |
| Tested end-to-end | Full `/query` endpoint returns correct responses via AI Core |

The LangGraph graph, HANA Cloud retrieval, CAP OData service, and Fiori UI are completely unchanged. SAP AI Core is a drop-in replacement for the model inference layer.
