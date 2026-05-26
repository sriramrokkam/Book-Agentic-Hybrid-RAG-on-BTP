# Chapter 3: Platform Setup — SAP BTP Trial + Google Vertex AI

## 3.1 The Goal of This Chapter

Before we write a single line of agent code, we need a working environment. This chapter gets you there.

By the end of this chapter, you will have:

- A running SAP BTP trial account with a HANA Cloud instance
- A GCP project with Vertex AI enabled and a service account ready
- A BTP Destination that securely connects your BTP applications to Vertex AI
- A local development environment with all required tools installed
- A confirmed, working API call to Gemini 2.5 Flash from your local machine

This is pure setup. There is no agent code here. But every chapter that follows depends on this foundation being solid. Rushing this chapter and skipping verification steps is the most common cause of confusing errors later. Take the 45 minutes. Do it properly.

> **Cost reminder:** Everything in this chapter is free. SAP BTP trial is free. GCP provides $300 credit on signup. The Vertex AI API calls in this chapter will cost cents — comfortably within the trial credit.

---

## 3.2 Understanding What We Are Setting Up

Before clicking through consoles, it helps to understand the shape of what we are building.

Our system has three infrastructure components:

```
┌─────────────────────────────────────────────────────────────┐
│  Your Local Machine                                          │
│  Python 3.11+  │  Node.js 20+  │  CF CLI  │  VS Code        │
└────────────────────────┬────────────────────────────────────┘
                         │ develops & deploys to
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  SAP BTP Trial Account (eu10 or us10 region)                │
│                                                              │
│  ┌─────────────────────┐   ┌────────────────────────────┐  │
│  │  Cloud Foundry Space │   │  HANA Cloud Instance        │  │
│  │  (free runtime)      │   │  ├─ REAL_VECTOR table       │  │
│  │  FastAPI agent       │   │  └─ SPARQL/RDF graphs       │  │
│  │  CAP Node.js service │   └────────────────────────────┘  │
│  └─────────────────────┘                                     │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Destination Service                                 │    │
│  │  "VertexAI" destination → GCP service account creds │    │
│  └─────────────────────────────────────────────────────┘    │
└────────────────────────┬────────────────────────────────────┘
                         │ calls (HTTPS only)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  Google Cloud Platform                                       │
│  ├─ Vertex AI API: text-embedding-004                       │
│  └─ Vertex AI API: Gemini 2.5 Flash                         │
└─────────────────────────────────────────────────────────────┘
```

SAP HANA Cloud is the **knowledge layer** — it stores both our vector embeddings and our RDF knowledge graph in a single managed service. No other database on the market provides both REAL_VECTOR column types (for cosine similarity search) and a native SPARQL execution engine in one service. This is a significant architectural advantage — one connection, one credential, two retrieval strategies.

Google Vertex AI is the **AI inference layer** — it is an external HTTPS API that our BTP application calls like any other REST service. Gemini 2.5 Flash handles both our LLM tasks (SPARQL generation, answer synthesis) and we use `text-embedding-004` for generating embeddings. The BTP Destination Service stores the GCP credentials securely — the service account JSON key never lives in application code or environment variables directly.

With this picture in mind, let us set it up.

---

## 3.3 SAP BTP Trial Account

### Signing Up

Navigate to `account.hanatrial.ondemand.com` and click **Try for Free**.

![SAP BTP Trial Signup](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/btp/01-btp-homepage.png)
*Figure: SAP BTP Trial — navigate to account.hanatrial.ondemand.com and click Try for Free*

Fill in your details. Use a personal email address if possible — corporate email addresses sometimes cause issues with trial account activation. After verifying your email, BTP will automatically provision a trial account in either the EU10 (Frankfurt) or US10 (Virginia) region depending on your location.

> **Note:** The region matters. Your HANA Cloud instance must be in the same region as your Cloud Foundry space. BTP assigns both automatically — do not change the region during signup.

Once logged in, you will land on the **BTP Cockpit** — the central control panel for all BTP services.

![SAP BTP Cockpit](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/btp/04-btp-trial-created.png)
*Figure: SAP BTP Cockpit home screen showing your Global Account and trial subaccount*

### Navigating to Your Trial Subaccount

The BTP Cockpit has a hierarchy: Global Account → Subaccount → Space. Your trial comes with one subaccount called "trial." Click it.

![BTP Subaccount Overview](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/btp/05-btp-subaccount.png)
*Figure: BTP trial subaccount overview page*

Inside the subaccount, you will see your **Cloud Foundry environment**. Note your CF API endpoint — it will look like `https://api.cf.eu10.hana.ondemand.com`. You will need this later.

Click **Cloud Foundry** → **Spaces**. You should see a space called "dev." This is where you will deploy your applications.

![BTP Cloud Foundry Spaces](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/hana/01-hana-subaccount.png)
*Figure: Cloud Foundry space view — note your org name and the "dev" space*

> **Write these down now:**
> - CF API Endpoint: `https://api.cf.<region>.hana.ondemand.com`
> - CF Org: `<your-trial-org>`
> - CF Space: `dev`

---

## 3.4 Provisioning SAP HANA Cloud

HANA Cloud is provisioned from the BTP Cockpit. This is a one-time setup that takes about 10–15 minutes.

### Creating the HANA Cloud Instance

From your trial subaccount, go to **Services** → **Service Marketplace**. Search for "HANA Cloud."

![BTP Service Marketplace](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/btp/06-btp-marketplace.png)
*Figure: BTP Service Marketplace — search for "HANA Cloud" to find the tile*

Click the HANA Cloud tile → **Create**. You will be taken to the HANA Cloud provisioning wizard.

Fill in the configuration:

| Field | Value |
|-------|-------|
| Instance Name | `hana-trial` |
| Administrator Password | Choose a strong password (save it!) |
| Memory | 30 GB (the trial default — do not reduce) |
| Storage | 120 GB (the trial default) |

![HANA Cloud Provisioning](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/hana/03-hana-create.png)
*Figure: HANA Cloud instance creation wizard — set instance name and keep default 30GB memory*

Click **Create**. Provisioning takes approximately 10–15 minutes. You will see the instance appear in the SAP HANA Cloud Central tool with a "Starting" status.

![HANA Cloud Central](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/hana/04-hana-central.png)
*Figure: SAP HANA Cloud Central showing the instance provisioning status*

Wait until the status shows **Running** before proceeding.

### Enabling the Vector Engine

By default, HANA Cloud provisions with the vector engine enabled in trial. To confirm, open **SAP HANA Cloud Central** → click your instance → **Manage HANA Cloud** → **Edit**.

Under **Additional Features**, verify that **Script Server** and **Document Store** are enabled. The vector engine (REAL_VECTOR column type) is part of the core engine — no separate flag is needed.

![HANA Cloud Central](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/hana/04-hana-central.png)
*Figure: HANA Cloud Central — click your instance to manage settings and verify vector engine availability*

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

## 3.5 Setting Up Google Cloud + Vertex AI

### Creating a GCP Account

Go to `cloud.google.com/free` and click **Get started for free**.

![GCP Free Tier](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/gcp/01-gcp-free-tier.png)
*Figure: Google Cloud free tier page — click "Get started for free" to claim your $300 credit*

Sign in with your Google account. GCP will ask for a credit card for identity verification — **you will not be charged** during the free trial, and the $300 credit covers everything in this book many times over.

After signup, you will land on the **GCP Console**.

![GCP Console](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/gcp/01-vertex-ai-overview.png)
*Figure: Google Cloud Console — your project selector appears in the top navigation bar*

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

### Creating a Service Account

Your BTP application needs credentials to call the Vertex AI API. GCP uses **service accounts** for machine-to-machine authentication. This is the right tool — not user accounts, not OAuth flows.

Go to **IAM & Admin** → **Service Accounts** → **Create Service Account**.

| Field | Value |
|-------|-------|
| Service Account Name | `agentic-rag-btp-sa` |
| Service Account ID | Auto-generated from `agentic-rag-btp-sa` |
| Description | `Service account for Agentic Hybrid RAG on SAP BTP` |

> **Note:** Navigate to IAM & Admin → Service Accounts → Create Service Account → enter name `hybrid-rag-sa` → Continue.

Click **Create and Continue**.

In Step 2 (Grant access), add the following role:

| Role | Purpose |
|------|---------|
| **Vertex AI User** | Allows calling Vertex AI APIs (LLM and embeddings) |

> **Note:** In the role assignment step, search for "Vertex AI User" and select it. Click Continue → Done.

Click **Continue** → **Done**.

### Downloading the Service Account Key

You will now download a JSON key file that contains the credentials your BTP application will use.

From the Service Accounts list, click the service account you just created → **Keys** tab → **Add Key** → **Create new key** → **JSON** → **Create**.

> **Note:** Click your service account → Keys tab → Add Key → Create new key → JSON → Create. The key file downloads automatically.

A JSON file will download automatically. It looks like this:

```json
{
  "type": "service_account",
  "project_id": "agentic-rag-btp",
  "private_key_id": "abc123...",
  "private_key": "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----\n",
  "client_email": "agentic-rag-btp-sa@agentic-rag-btp.iam.gserviceaccount.com",
  "client_id": "123456789",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token"
}
```

> **Warning:** This file contains your private key. Treat it like a password. Do not commit it to git. Do not share it. Store it somewhere safe on your machine — we will upload it to BTP Destination Service in the next section, and then you will not need it in plaintext again.

Save the file as `gcp-sa-key.json` in a secure location outside your project directory.

---

## 3.6 Configuring the BTP Destination Service

The BTP Destination Service is the secure credential store that connects your BTP applications to external services. Your FastAPI agent will read the Vertex AI credentials from this destination at runtime — the JSON key never lives in application code or in `manifest.yml`.

This is the SAP-native way to manage external service credentials, and it is an important pattern to understand. As Albada notes in *Building Applications with AI Agents*, modularity is essential in agent system design — your agent should be able to swap its LLM provider by changing a destination configuration, not by redeploying code.

### Creating the Destination

In the BTP Cockpit, go to your trial subaccount → **Connectivity** → **Destinations** → **New Destination**.

![BTP Entitlements](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/hana/02-hana-entitlements.png)
*Figure: BTP Connectivity → Destinations — click "New Destination" to create the Vertex AI destination*

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

## 3.7 Local Development Environment

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

## 3.8 Project Setup

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

> **Note:** The `GOOGLE_APPLICATION_CREDENTIALS` environment variable is only used for local development. When deployed to BTP Cloud Foundry, the agent reads credentials from the Destination Service instead. We will see this credential-switching logic in Chapter 10.

---

## 3.9 Verifying the Setup: Your First Gemini API Call

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

> **Note:** The dimension 768 is important. When we create the HANA Cloud vector table in Chapter 3, we will define the column as `REAL_VECTOR(768)`. If you switch embedding models later, you must recreate the table — the dimension is fixed at table creation time.

---

## 3.10 Verifying the HANA Cloud Connection

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

## 3.11 What We Have Built

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

## 3.12 Understanding the Credential Flow

Before we move on, it is worth understanding exactly how credentials flow through the system. This will matter in Chapter 10 when you deploy to BTP, and it is a pattern that comes up repeatedly in enterprise AI systems.

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

We will build `vertex_srv.py` in Chapter 3. For now, knowing the pattern exists is enough.

---

## 3.13 Summary

- SAP BTP trial provides free Cloud Foundry runtime and HANA Cloud — the only database that combines vector search and SPARQL knowledge graph in one service
- Google Vertex AI is an external HTTPS API — no GPU management, no model hosting, just an API call from BTP CF
- The BTP Destination Service stores GCP credentials securely — never in code, never in `manifest.yml`
- `text-embedding-004` produces 768-dimensional embeddings — this dimension is fixed and determines the HANA vector table schema
- Both the Gemini API call and the HANA Cloud connection are now verified end-to-end

In Chapter 3, we build the first half of our knowledge layer: vector search on SAP HANA Cloud. We will create the `MSDS_VECTORS` table, implement the embedding pipeline using `text-embedding-004`, and run our first semantic similarity search — the same operation our hybrid RAG agent will use at query time.
