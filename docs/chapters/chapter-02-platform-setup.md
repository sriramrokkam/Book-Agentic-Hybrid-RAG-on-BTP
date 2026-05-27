# Chapter 2: Platform Setup — SAP BTP Trial + Google Vertex AI

## 2.1 The Goal of This Chapter

Before we write a single line of agent code, we need a working environment. This chapter gets you there.

By the end of this chapter, you will have:

- A running SAP BTP trial account with a HANA Cloud instance
- A GCP project with Vertex AI enabled and a service account ready
- A BTP Destination that securely connects your BTP applications to Vertex AI
- A local development environment with all required tools installed
- A confirmed, working API call to Gemini 2.5 Flash from your local machine

This is pure setup. There is no agent code here. But every chapter that follows depends on this foundation being solid. Rushing this chapter and skipping verification steps is the most common cause of confusing errors later. Take the 45 minutes. Do it properly.

> **Cost:** SAP BTP trial is free. GCP provides $300 credit on signup — the Vertex AI API calls for this entire project cost a few dollars at most. The same setup steps apply to a paid BTP account; the only difference is the account URL.

---

## 2.2 Understanding What We Are Setting Up

Before clicking through consoles, it helps to understand the shape of what we are building.

Our system has three infrastructure components:

![Platform Setup Overview](docs/screenshots/diagrams/02-platform-setup-overview.png)
*Figure 2.2 — Your local machine develops and deploys to SAP BTP Trial. The BTP Cloud Foundry space runs the FastAPI agent and CAP Node.js service. HANA Cloud holds the REAL_VECTOR table and SPARQL/RDF graphs. The Destination Service stores GCP credentials. All Vertex AI calls go outbound over HTTPS only.*

SAP HANA Cloud is the **knowledge layer** — it stores both our vector embeddings and our RDF Knowledge Graph in a single managed service. No other database on the market provides both REAL_VECTOR column types (for cosine similarity search) and a native SPARQL execution engine in one service. This is a significant architectural advantage — one connection, one credential, two retrieval strategies.

Google Vertex AI is the **AI inference layer** — it is an external HTTPS API that our BTP application calls like any other REST service. Gemini 2.5 Flash handles both our LLM tasks (SPARQL generation, answer synthesis) and we use `text-embedding-004` for generating embeddings. The BTP Destination Service stores the GCP credentials securely — the service account JSON key never lives in application code or environment variables directly.

With this picture in mind, let us set it up.

---

## 2.3 SAP BTP Trial Account

### Signing Up

Navigate to `https://www.sap.com/products/technology-platform/trial.html` and click **Try now**.

![SAP BTP Trial Signup](docs/screenshots/btp/01-btp-homepage.png)
*Figure 2.1 — SAP BTP Free Trial landing page — click "Try now" to start your free trial account*

Fill in your details. Use a personal email address if possible — corporate email addresses sometimes cause issues with trial account activation. After verifying your email, BTP will automatically provision a trial account in either the EU10 (Frankfurt) or US10 (Virginia) region depending on your location.

> **Note:** The region matters. Your HANA Cloud instance must be in the same region as your Cloud Foundry space. BTP assigns both automatically — do not change the region during signup.

Once logged in, you will land on the **BTP Cockpit** — the central control panel for all BTP services.

![SAP BTP Cockpit](docs/screenshots/btp/04-btp-trial-created.png)
*Figure: SAP BTP Cockpit home screen showing your Global Account and trial subaccount*

### Navigating to Your Trial Subaccount

The BTP Cockpit has a hierarchy: Global Account → Subaccount → Space. Your trial comes with one subaccount called "trial." Click it.

![BTP Subaccount Overview](docs/screenshots/btp/05-btp-subaccount.png)
*Figure: BTP trial subaccount overview page*

Inside the subaccount, you will see your **Cloud Foundry environment**. Note your CF API endpoint — it will look like `https://api.cf.eu10.hana.ondemand.com`. You will need this later.

Click **Cloud Foundry** → **Spaces**. You should see a space called "dev." This is where you will deploy your applications.

![BTP Cloud Foundry Spaces](docs/screenshots/hana/01-hana-subaccount.png)
*Figure: Cloud Foundry space view — note your org name and the "dev" space*

> **Write these down now:**
> - CF API Endpoint: `https://api.cf.<region>.hana.ondemand.com`
> - CF Org: `<your-trial-org>`
> - CF Space: `dev`

---

## 2.4 Provisioning SAP HANA Cloud

HANA Cloud is provisioned from the BTP Cockpit. This is a one-time setup that takes about 10–15 minutes.

### Creating the HANA Cloud Instance

From your trial subaccount, go to **Services** → **Service Marketplace**. Search for "HANA Cloud."

![BTP Service Marketplace](docs/screenshots/btp/06-btp-marketplace.png)
*Figure: BTP Service Marketplace — search for "HANA Cloud" to find the tile*

Click the HANA Cloud tile → **Create**. You will be taken to the HANA Cloud provisioning wizard.

Fill in the configuration:

| Field | Value |
|-------|-------|
| Instance Name | `hana-trial` |
| Administrator Password | Choose a strong password (save it!) |
| Memory | 30 GB (the trial default — do not reduce) |
| Storage | 120 GB (the trial default) |

![HANA Cloud Provisioning](docs/screenshots/hana/03-hana-create.png)
*Figure: HANA Cloud instance creation wizard — set instance name and keep default 30GB memory*

Click **Create**. Provisioning takes approximately 10–15 minutes. You will see the instance appear in the SAP HANA Cloud Central tool with a "Starting" status.

![HANA Cloud Central](docs/screenshots/hana/04-hana-central.png)
*Figure: SAP HANA Cloud Central showing the instance provisioning status*

Wait until the status shows **Running** before proceeding.

### Enabling the Vector Engine

By default, HANA Cloud provisions with the vector engine enabled in trial. To confirm, open **SAP HANA Cloud Central** → click your instance → **Manage HANA Cloud** → **Edit**.

Under **Additional Features**, verify that **Script Server** and **Document Store** are enabled. The vector engine (REAL_VECTOR column type) is part of the core engine — no separate flag is needed.

![HANA Cloud Central](docs/screenshots/hana/04-hana-central.png)
*Figure: HANA Cloud Central — click your instance to manage settings and verify vector engine availability*

### Enabling the Knowledge Graph Engine

The RDF/SPARQL engine in HANA Cloud is the **Triple Store** — and it is not enabled by default. Without it, all SPARQL queries in Chapters 4, 5, 7, and 8 will fail silently. This is the single most common setup mistake.

**The correct feature to enable is Triple Store — not Document Store.**

You can enable it on a running instance at any time — no delete or recreate required. In HANA Cloud Central:

1. Click your instance name → the dropdown chevron next to the instance name → **Manage Configuration**
2. Select the **Advanced Settings** tab
3. Under **Additional Features**, check **Triple Store**
4. Optionally check **Script Server** if you plan to use other stored procedures
5. Click **Save** — HANA Cloud applies the change without downtime

![HANA Cloud Advanced Settings — Triple Store](docs/screenshots/hana/hana-advanced-settings-triple-store.png)
*Figure 2.x — HANA Cloud Central → your instance → Manage Configuration → Advanced Settings. Enable Triple Store (the RDF/SPARQL engine). Script Server is separate. Document Store is for JSON documents — not required for this book.*

> **Important:** The info banner on this screen says "Adding features to an instance may require more memory and increase your licensing cost." On a trial instance, enabling Triple Store is free within the trial allocation. Monitor your CU usage in HANA Cloud Central if you are concerned.

> **Note:** Natural Language Processing (NLP) is shown as enabled in the screenshot above — that is from a separate training instance. You do not need NLP enabled for this book.

### Getting Your HANA Connection Details

From SAP HANA Cloud Central, click your instance → **Actions** → **Copy SQL Endpoint**.

This gives you a connection string like:
```
<instance-id>.hana.trial-us10.hanacloud.ondemand.com:443
```

Save these:
- **Host:** `<instance-id>.hana.trial-<region>.hanacloud.ondemand.com`
- **Port:** `443`
- **User:** `DBADMIN`
- **Password:** The password you set during provisioning

> **Warning:** The DBADMIN user has full database privileges. For production, create a dedicated application user with limited permissions. For this book's trial environment, DBADMIN is acceptable.

---

## 2.5 Setting Up Google Cloud + Vertex AI

Vertex AI is the model inference layer for this book — Gemini 2.5 Flash for LLM tasks, `text-embedding-004` for vector embeddings. We use it because it is immediately accessible with a Google account and $300 free credit, making it available to every reader regardless of SAP subscription level. The agent architecture is provider-agnostic; Appendix E shows how to swap in SAP AI Core for enterprise deployments where that is the preferred inference platform.

### Creating a GCP Account

Go to `cloud.google.com/free` and click **Get started for free**.

Sign in with your Google account.

> **Important — Credit Card Required:** GCP will ask for credit card details during signup for identity verification. A charge will not be made immediately, but a card is mandatory to activate the $300 free credit. Read GCP's terms and conditions carefully before proceeding — billing behaviour, credit expiry, and auto-upgrade conditions are your responsibility to understand.

> **Caution — Use Your $300 Credit Wisely:** The exercises in this book are well within the $300 free credit — typical usage for the full project (embeddings, Gemini API calls, SPARQL generation) costs a few dollars at most. However, once you complete this project, **delete your GCP project and suspend or close your GCP account within 90 days**. An idle project with APIs enabled can accrue unexpected charges. Cleaning up after the exercise is not optional — it is good practice. Steps to delete your project are in Appendix B. Managing your GCP account beyond this book's exercises is outside the scope of this book.

After signup, you will land on the **GCP Console**.

*Screenshot pending: GCP Console home page showing the project selector in the top navigation bar and Vertex AI API enabled.*

### Creating a New Project

Click the project selector at the top of the page → **New Project**.

| Field | Value |
|-------|-------|
| Project Name | `agentic-rag-btp` |
| Project ID | Auto-generated (note this down) |
| Organization | No organization (personal account) |

> **Note:** In GCP Console, click the project selector dropdown → "New Project" → enter a project name (e.g. `hybrid-rag-btp`) → Create.

Click **Create**. Wait a few seconds for the project to be created, then select it from the project selector.

### Enabling the Vertex AI API

In the GCP Console, go to **APIs & Services** → **Library**. Search for "Vertex AI API."

> **Note:** Navigate to APIs & Services → Library → search "Vertex AI API" → click Enable.

Click the Vertex AI API tile → **Enable**.

> **Note:** After enabling, the Vertex AI API page will show a green checkmark and "API enabled" status.

Enabling the API takes about 30 seconds. Once enabled, you will see the Vertex AI API dashboard.

> **Note:** Enabling Vertex AI automatically enables several dependent APIs (Cloud Storage, Cloud Resource Manager, etc.). This is expected.

### GCP Authentication — What Actually Works

**Use a personal Google account for this book.** Sign up at `cloud.google.com/free` with a personal Gmail — not your corporate Google Workspace account. Corporate GCP organisations typically block service account key creation via org policy, which will prevent the steps below from working.

This book uses two authentication approaches depending on context:

| Context | Method |
|---------|--------|
| Local development (Chapters 2–9) | Application Default Credentials via `gcloud` CLI |
| BTP Cloud Foundry deployment (Chapter 10) | Service account JSON key via BTP Destination Service |

### Creating a Service Account

Go to **IAM & Admin** → **Service Accounts** → **Create Service Account**.

| Field | Value |
|-------|-------|
| Service Account Name | `agentic-rag-btp-sa` |
| Service Account ID | Auto-generated |
| Description | `Service account for Agentic Hybrid RAG on SAP BTP` |

Click **Create and Continue**. In the role assignment step, add:

| Role | Purpose |
|------|---------|
| **Vertex AI User** | Calling Vertex AI APIs (Gemini LLM + text-embedding-004) |

Click **Continue** → **Done**.

### Option A — Local Development: Application Default Credentials (ADC)

For Chapters 2–9, running the FastAPI agent locally, use ADC. No JSON key file is downloaded or stored.

Install the gcloud CLI from `cloud.google.com/sdk/docs/install`, then run:

```bash
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

Your browser opens a Google login page. Sign in with your personal Google account. The gcloud CLI stores credentials at:

```
~/.config/gcloud/application_default_credentials.json   # macOS/Linux
%APPDATA%\gcloud\application_default_credentials.json   # Windows
```

The Vertex AI Python SDK picks these up automatically — no `GOOGLE_APPLICATION_CREDENTIALS` environment variable needed. Your `.env` file only needs:

```bash
GOOGLE_CLOUD_PROJECT=your-project-id
GCP_LOCATION=us-central1
```

> **How ADC works:** The Vertex AI SDK checks for credentials in this order: (1) `GOOGLE_APPLICATION_CREDENTIALS` env var, (2) ADC file from `gcloud auth application-default login`, (3) attached service account metadata. For local development, step 2 handles it automatically. Official reference: `cloud.google.com/docs/authentication/application-default-credentials`

### Option B — BTP Cloud Foundry Deployment: API Key

When you deploy to BTP CF in Chapter 10, the container has no gcloud CLI and no access to your local ADC file. Use a GCP API key scoped to Vertex AI.

In GCP Console → **APIs & Services** → **Credentials** → **Create Credentials** → **API Key**.

Once created, click **Edit API Key** and restrict it:

| Setting | Value |
|---------|-------|
| API restrictions | Restrict key → Vertex AI API |
| Application restrictions | None (for CF deployment) |

Copy the key value. You will set it as a CF environment variable in Chapter 10:

```bash
cf set-env agentic-rag-backend GOOGLE_API_KEY "AIza..."
```

> **Never put the API key in `manifest.yml` or commit it to git.** Set it via `cf set-env` only. The key value is never written to any file in the repository.

> **Note:** If you later need to rotate or revoke the key, go to APIs & Services → Credentials → select the key → Delete. A new key can be generated in under a minute.

---

## 2.6 Configuring the BTP Destination Service

The BTP Destination Service is the secure credential store that connects your BTP applications to external services. Your FastAPI agent will read the Vertex AI credentials from this destination at runtime — the JSON key never lives in application code or in `manifest.yml`.

This is the SAP-native way to manage external service credentials, and it is an important pattern to understand from an enterprise architecture perspective. In BTP enterprise architecture, the Destination Service is the standard pattern for externalising all external API credentials — your agent switches AI providers by changing a destination configuration in the BTP Cockpit, not by touching application code or triggering a redeployment. This is the same pattern used for S/4HANA connectivity, external REST APIs, and OAuth token exchange across the entire BTP portfolio. In a landscape where dozens of BTP applications may share the same external service connection, this centralised approach also simplifies credential governance and audit trails — both of which matter in regulated industries.

### Creating the Destination

In the BTP Cockpit, go to your trial subaccount → **Connectivity** → **Destinations** → **New Destination**.

*Screenshot pending: BTP Cockpit → Connectivity → Destinations — the New Destination button and the configured VertexAI destination entry.*

Fill in the destination configuration:

| Field | Value |
|-------|-------|
| Name | `VertexAI` |
| Type | `HTTP` |
| Description | `Google Vertex AI API (Gemini + Embeddings)` |
| URL | `https://us-central1-aiplatform.googleapis.com` |
| Proxy Type | `Internet` |
| Authentication | `NoAuthentication` |

Click **New Property** to add these additional properties:

| Property | Value |
|----------|-------|
| `gcp.project_id` | Your GCP project ID (e.g., `agentic-rag-btp`) |
| `gcp.location` | `us-central1` |
| `gcp.service_account_key` | The **entire contents** of your `gcp-sa-key.json` file, pasted as a single string |

> **Note:** Fill in all destination fields as shown in the table above. Paste your GCP service account JSON key into the token service URL credentials field.

Click **Save**, then click **Check Connection**. You should see a green "200 OK" response.

> **Tip:** After saving, click "Check Connection" at the bottom of the destination form. A "200 OK" response confirms the credentials are valid.

> **Note:** The `gcp.service_account_key` property stores the raw JSON — not a file path. Open `gcp-sa-key.json` in a text editor, select all, copy, and paste the entire JSON object into the property value field. BTP encrypts this value at rest.

---

## 2.7 Local Development Environment

Now set up your local machine. We need Python, Node.js, the CF CLI, the CDS CLI, and VS Code.

### Python 3.11+

Verify your Python version:

```bash
python3 --version
# Should output: Python 3.11.x or 3.12.x
```

If you need to install Python, download it from `python.org/downloads`. On macOS with Homebrew:

```bash
brew install python@3.11
```

### Node.js 20+

Verify:

```bash
node --version   # Should output: v20.x.x or higher
npm --version    # Should output: 10.x.x or higher
```

Install from `nodejs.org` if needed. On macOS:

```bash
brew install node@20
```

### Cloud Foundry CLI

The CF CLI is how you deploy your application to BTP Cloud Foundry.

```bash
# macOS (Homebrew)
brew install cloudfoundry/tap/cf-cli@8

# Verify
cf --version
# Cloud Foundry CLI version 8.x.x
```

For other platforms, download from the [CF CLI releases page](https://github.com/cloudfoundry/cli/releases).

> **Why Cloud Foundry?** This book deploys to BTP Cloud Foundry because it is the simplest path to a running service — `cf push`, no container registry, no Kubernetes manifests. For production-grade agentic architectures requiring horizontal pod scaling, multi-agent process isolation, or A2A communication across microservices, **Kyma runtime** (BTP's managed Kubernetes environment) is the right deployment target. That is a separate book.

Log in to your BTP CF environment:

```bash
cf login -a https://api.cf.<your-region>.hana.ondemand.com
# Enter your BTP email and password
# Select the "trial" org and "dev" space
```

> **Note:** After `cf login`, you will be prompted to select your org (your trial org name) and space (`dev`). Select the correct ones and press Enter.

Verify the login:

```bash
cf target
# Should show:
# API endpoint:   https://api.cf.eu10.hana.ondemand.com
# API version:    3.x.x
# user:           your@email.com
# org:            your-trial-org
# space:          dev
```

### SAP CDS CLI

The CDS CLI is the development tool for CAP Node.js applications.

```bash
npm install -g @sap/cds-dk

# Verify
cds --version
# @sap/cds-dk: 8.x.x
```

### VS Code Extensions

Open VS Code and install these extensions:

| Extension | Publisher | Purpose |
|-----------|-----------|---------|
| SAP CDS Language Support | SAP | CDS syntax highlighting and validation |
| Python | Microsoft | Python IntelliSense and debugging |
| REST Client | Humao | Test API endpoints without Postman |

> **Tip:** In VS Code, press `Cmd+Shift+X` to open Extensions. Search for each extension name and click Install.

---

## 2.8 Project Setup

Clone the companion repository and set up the Python environment for the agent service:

```bash
git clone https://github.com/sriramrokkam/agentic-rag-btp-book
cd agentic-rag-btp-book/agents

python3 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

The `requirements.txt` for the agent service contains:

```text
fastapi==0.111.0
uvicorn[standard]==0.30.1
langgraph==0.2.0
langchain-google-vertexai==1.0.6
google-auth==2.29.0
hdbcli==2.21.28
PyMuPDF==1.24.5
python-multipart==0.0.9
httpx==0.27.0
```

Create your local environment file:

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```bash
# SAP HANA Cloud
HANA_HOST=<your-instance>.hana.trial-<region>.hanacloud.ondemand.com
HANA_PORT=443
HANA_USER=DBADMIN
HANA_PASSWORD=<your-hana-password>

# Google Vertex AI (local development only)
# On BTP, credentials come from the Destination Service
GCP_PROJECT_ID=agentic-rag-btp
GCP_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=/path/to/gcp-sa-key.json

# Backend URL (for CAP service to call the FastAPI agent)
BACKEND_URL=http://localhost:8000
```

> **Note:** The `GOOGLE_APPLICATION_CREDENTIALS` environment variable is only used for local development. When deployed to BTP Cloud Foundry, the agent reads credentials from the Destination Service instead. We will see this credential-switching logic in Chapter 9.

---

## 2.9 Verifying the Setup: Your First Gemini API Call

Let us verify that everything works end-to-end. We will call Gemini 2.5 Flash directly and confirm we get a response.

Create a file `test_vertex.py` in your `agents/` directory:

```python
import os
from dotenv import load_dotenv
import vertexai
from vertexai.generative_models import GenerativeModel

load_dotenv()

# Initialize Vertex AI with project and location
vertexai.init(
    project=os.getenv("GCP_PROJECT_ID"),
    location=os.getenv("GCP_LOCATION"),
)

# Load Gemini 2.5 Flash
model = GenerativeModel("gemini-2.5-flash-preview-05-20")

# Send a simple test prompt
response = model.generate_content(
    "You are a helpful assistant for SAP developers. "
    "In one sentence, explain what a Material Safety Data Sheet (MSDS) is."
)

print("Gemini response:")
print(response.text)
print("\nModel used: gemini-2.5-flash-preview-05-20")
print("Setup verified successfully.")
```

Run it:

```bash
python test_vertex.py
```

You should see output like:

```
Gemini response:
A Material Safety Data Sheet (MSDS) is a standardized document that provides
detailed information about the properties, hazards, safe handling procedures,
and emergency response measures for a chemical substance or mixture.

Model used: gemini-2.5-flash-preview-05-20
Setup verified successfully.
```

```
# Expected terminal output:
VertexAI initialized successfully
Model loaded: gemini-2.5-flash
Response: The capital of France is Paris.
Vertex AI connection: OK
```

> **If you see an error:** The most common issues are:
> - `google.auth.exceptions.DefaultCredentialsError` — Check that `GOOGLE_APPLICATION_CREDENTIALS` points to the correct JSON file path
> - `Permission denied on resource` — Verify the service account has the **Vertex AI User** role in GCP IAM
> - `API not enabled` — Return to the GCP Console and confirm the Vertex AI API is enabled for your project

Now verify the embedding model:

```python
# Add to test_vertex.py

from vertexai.language_models import TextEmbeddingModel

embedding_model = TextEmbeddingModel.from_pretrained("text-embedding-004")

test_texts = [
    "What is the flash point of acetone?",
    "GHS hazard classification for flammable liquids"
]

embeddings = embedding_model.get_embeddings(test_texts)

for text, embedding in zip(test_texts, embeddings):
    print(f"\nText: {text[:50]}...")
    print(f"Embedding dimension: {len(embedding.values)}")
    print(f"First 5 values: {embedding.values[:5]}")
```

The output should show embeddings with dimension 768 (the dimension of `text-embedding-004`):

```
Text: What is the flash point of acetone?...
Embedding dimension: 768
First 5 values: [0.023, -0.041, 0.018, 0.067, -0.029]

Text: GHS hazard classification for flammable liquids...
Embedding dimension: 768
First 5 values: [0.031, -0.038, 0.022, 0.054, -0.011]
```

> **Note:** The dimension 768 is important. When we create the HANA Cloud vector table in Chapter 2, we will define the column as `REAL_VECTOR(768)`. If you switch embedding models later, you must recreate the table — the dimension is fixed at table creation time.

---

## 2.10 Verifying the HANA Cloud Connection

Run a quick connectivity test to confirm HANA Cloud is reachable:

```python
# test_hana.py
import os
from dotenv import load_dotenv
from hdbcli import dbapi

load_dotenv()

conn = dbapi.connect(
    address=os.getenv("HANA_HOST"),
    port=int(os.getenv("HANA_PORT")),
    user=os.getenv("HANA_USER"),
    password=os.getenv("HANA_PASSWORD"),
    encrypt=True,
    sslValidateCertificate=False
)

cursor = conn.cursor()
cursor.execute("SELECT VERSION FROM SYS.M_DATABASE")
version = cursor.fetchone()[0]
print(f"Connected to SAP HANA Cloud version: {version}")

# Verify vector engine is available
cursor.execute("""
    SELECT COUNT(*) FROM SYS.M_FEATURE_USAGE
    WHERE FEATURE_NAME = 'VECTOR'
""")
vector_count = cursor.fetchone()[0]
if vector_count > 0:
    print("Vector engine: Available")
else:
    print("Vector engine: Not detected (check HANA Cloud instance settings)")

cursor.close()
conn.close()
print("\nHANA Cloud connection verified.")
```

```bash
python test_hana.py
```

Expected output:

```
Connected to SAP HANA Cloud version: 4.00.000.00.1698...
Vector engine: Available
HANA Cloud connection verified.
```

```
# Expected terminal output:
HANA version: 4.00.000.00.1234567890 (fa/CE2024)
Vector engine: Available
SPARQL engine: Available
HANA connection: OK
```

---

## 2.11 What We Have Built

Let us take stock of what is now in place:

| Component | Status | Where |
|-----------|--------|-------|
| BTP trial account | Running | account.hanatrial.ondemand.com |
| CF space "dev" | Ready | BTP Cockpit → Cloud Foundry |
| HANA Cloud instance | Running | BTP Cockpit → HANA Cloud Central |
| GCP project | Active | console.cloud.google.com |
| Vertex AI API | Enabled | GCP Console → APIs & Services |
| GCP service account | Created | GCP Console → IAM & Admin |
| BTP Destination "VertexAI" | Configured | BTP Cockpit → Connectivity |
| Python environment | Active | `agents/.venv` |
| Gemini API call | Verified | `test_vertex.py` passed |
| HANA connection | Verified | `test_hana.py` passed |

This is not a small setup. You now have a working hybrid cloud environment: a managed in-memory database with vector and graph capabilities on BTP, connected to a frontier AI inference API on GCP, with credentials managed securely through BTP's Destination Service.

The architecture you set up here mirrors how SAP customers deploy AI at scale — not a toy environment, but the real stack.

---

## 2.12 Understanding the Credential Flow

Before we move on, it is worth understanding exactly how credentials flow through the system. This will matter in Chapter 9 when you deploy to BTP, and it is a pattern that comes up repeatedly in enterprise AI systems.

```
Local development:
  .env file → GOOGLE_APPLICATION_CREDENTIALS
  → google-auth library reads the JSON key directly
  → Vertex AI API call authenticated

BTP Cloud Foundry deployment:
  BTP Destination Service "VertexAI"
  → agents/srv/vertex_srv.py reads via CF environment
  → google-auth constructs credentials from the stored JSON
  → Vertex AI API call authenticated
```

The key insight is that **the application code never changes** between local and deployed. The credential source changes — `.env` locally, Destination Service in production — but the interface that `vertex_srv.py` exposes to the rest of the system is identical. This is the modularity principle in practice.

We will build `vertex_srv.py` in Chapter 2. For now, knowing the pattern exists is enough.

---

## 2.13 Summary

- SAP BTP trial provides free Cloud Foundry runtime and HANA Cloud — the only database that combines vector search and SPARQL Knowledge Graph in one service
- Google Vertex AI is an external HTTPS API — no GPU management, no model hosting, just an API call from BTP CF
- The BTP Destination Service stores GCP credentials securely — never in code, never in `manifest.yml`
- `text-embedding-004` produces 768-dimensional embeddings — this dimension is fixed and determines the HANA vector table schema
- Both the Gemini API call and the HANA Cloud connection are now verified end-to-end

In Chapter 3, we build the first half of our knowledge layer: vector search on SAP HANA Cloud. We will create the `MSDS_VECTORS` table, implement the embedding pipeline using `text-embedding-004`, and run our first semantic similarity search — the same operation our hybrid RAG agent will use at query time.
