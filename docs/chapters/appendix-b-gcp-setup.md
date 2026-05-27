# Appendix B: Google Cloud Setup — Vertex AI, Gemini, and Service Accounts

---

> **When to read this appendix.** Chapter 2 walks through the full platform setup at a brisk pace. If you have worked with GCP before, Chapter 2 gives you everything you need. If GCP is new to you — or if you want the full step-by-step with security guidance — work through this appendix first, then return to Chapter 2. This appendix covers the same GCP steps in greater depth.

---

## B.1 What You Will Have at the End

This appendix has a single, concrete goal: by the time you reach the verification checklist in section B.8, you will have:

1. A GCP project named `msds-hybrid-rag` (or any name you choose) with a Project ID recorded in your notes.
2. The Generative Language API and the Vertex AI API both enabled in that project.
3. Either an API key **or** a service account JSON key — the two authentication options are explained below, and you will choose one based on your situation.
4. A working Python test that calls `gemini-2.5-flash-preview-05-20` and receives a response.
5. A `.env` file in the `agents/` directory with the correct environment variable set.

Nothing here costs money. GCP provides $300 USD in free credits when you activate a new account, and the total API usage for the MSDS demo in this book will cost under one dollar.

---

## B.2 Two Authentication Options — Choose Before You Start

Before touching the GCP console, decide which authentication approach you will use. The book uses both at different stages: Option A locally, Option B for BTP Cloud Foundry deployment.

**Option A: API Key**

An API key is a string that begins with `AIza`. You pass it as the environment variable `GOOGLE_API_KEY`. The `google-generativeai` Python SDK reads this variable automatically when you call `genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))`.

- Simpler to set up (two minutes, no JSON file).
- Suitable for local development and personal experimentation.
- Appropriate for anyone reading this book to learn the concepts.
- Not recommended for production BTP deployments — the key has no fine-grained scope binding and is easy to leak if you are not careful.

**Option B: Service Account JSON Key**

A service account is a non-human Google identity (e.g., `msds-rag-agent@your-project.iam.gserviceaccount.com`). You assign it the `Vertex AI User` role, then download a JSON key file. The file path is passed as `GOOGLE_APPLICATION_CREDENTIALS`. The Google SDK reads this path and authenticates all API calls using it.

- More complex to set up (about ten minutes).
- Strongly recommended for BTP Cloud Foundry deployment — the JSON key is stored as a BTP secret or as a Destination Service credential and never embedded in application code.
- Allows fine-grained IAM role binding, audit logging, and key rotation.

**Which to use:** If you are working through this book on a laptop for the first time, use Option A. When you reach Chapter 10 (BTP Deployment), the deployment guide will instruct you to create a service account at that point. If you want to complete all steps now, do Option A first to verify the connection, then follow section B.6 to create the service account.

---

## B.3 Step 1 — Create a GCP Account

Open a browser and navigate to [https://cloud.google.com](https://cloud.google.com).

If you have a Google account (Gmail, Google Workspace), click **Get started for free** and sign in with that account. If you do not have a Google account, create one first at [https://accounts.google.com/signup](https://accounts.google.com/signup).

GCP requires a credit card or debit card to activate the free trial. The card is used for identity verification — you will not be charged during the trial period. Google is explicit about this: you must manually upgrade to a paid account after the $300 credit is exhausted. Until you do, billing is suspended and no charges are made.

Work through the activation form:

1. Agree to the Terms of Service.
2. Choose your country and confirm it matches your billing address.
3. Enter your payment details.
4. Click **Start my free trial**.

After activation, you are taken to the GCP Console at [https://console.cloud.google.com](https://console.cloud.google.com). The banner at the top will confirm your free trial credit.

![GCP free tier activation page](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/gcp/01-gcp-free-tier.png)

> **Note on existing GCP accounts.** If you already have a GCP account and have used the $300 credit, you can still follow this appendix. Create a new project under your existing account. Any Gemini API calls will be billed at the standard rate, but the cost for the MSDS demo is under one dollar.

---

## B.4 Step 2 — Create a New Project

Every GCP resource — APIs, credentials, service accounts, billing — lives inside a project. Create a dedicated project for this book's work.

In the GCP Console, look at the top navigation bar. You will see a project selector dropdown, which may say "My First Project" or the name of an existing project. Click it.

A dialog opens showing your existing projects. Click **New Project** in the upper-right corner of the dialog.

Fill in the form:

- **Project name:** `msds-hybrid-rag` (or any name — the name is for display only and can be changed later)
- **Organization:** Leave as "No organization" unless you are working inside a corporate Google Workspace account.
- **Location:** Leave as "No organization" for personal accounts.

Click **Create**. GCP will take about twenty seconds to provision the project.

Once created, use the project selector dropdown to switch to the new project. Confirm the project name appears in the top navigation bar.

**Record the Project ID.** The Project ID is different from the Project Name. It is a lowercase string, often `msds-hybrid-rag` followed by a number suffix (e.g., `msds-hybrid-rag-423901`). Find it on the project dashboard or in the project selector dialog. You will use this as `GCP_PROJECT_ID` in your `.env` file.

*[Screenshot: GCP new project creation form]*

---

## B.5 Step 3 — Enable the APIs

GCP APIs are not active by default. You must explicitly enable each one you intend to use. This is a deliberate security design — it limits the attack surface of each project.

This book uses two APIs:

- **Generative Language API** — provides the `gemini-2.5-flash-preview-05-20` model and `text-embedding-004` via the `google-generativeai` Python SDK.
- **Vertex AI API** — provides the same models via the `langchain-google-genai` and `vertexai` SDKs, and is required for the BTP deployment configuration in Chapter 10.

Enable both now. It takes about two minutes each.

**Enable the Generative Language API:**

1. In the left navigation, click **APIs & Services** > **Library**.
2. In the search box, type `Generative Language API`.
3. Click the result titled "Generative Language API."
4. Click **Enable**. The button will change to "Manage" once activation completes.

**Enable the Vertex AI API:**

1. Return to **APIs & Services** > **Library**.
2. Search for `Vertex AI API`.
3. Click **Vertex AI API** in the results.
4. Click **Enable**.

After both are enabled, go to **APIs & Services** > **Enabled APIs & Services** to confirm both appear in the list.

[SCREENSHOT: APIs & Services library showing search results for "Generative Language API" with the Enable button visible. Second screenshot: Enabled APIs list showing both "Generative Language API" and "Vertex AI API" with green status.]

---

## B.6 Step 4A — Get an API Key (Option A — Recommended for Local Development)

If you are using Option A authentication, follow these steps to create an API key.

1. In the left navigation, click **APIs & Services** > **Credentials**.
2. Click **+ Create Credentials** at the top of the page.
3. Select **API Key** from the dropdown.

GCP creates the key immediately and shows it in a dialog. **Copy the key now.** The full key value is shown only once in this dialog. After you close the dialog, you can still find the key in the Credentials list, but to see the full value again you must click into it. Copy it to a temporary notepad before closing.

**Restrict the key (strongly recommended):**

An unrestricted API key can be used to call any Google API in your project. Restrict it to the Generative Language API:

1. In the Credentials list, click the pencil icon next to your new key.
2. Under **API restrictions**, select **Restrict key**.
3. In the dropdown, select **Generative Language API**.
4. Click **Save**.

[SCREENSHOT: GCP Credentials page showing the API Key creation dialog with the key value visible. Second screenshot: API key restriction settings showing "Generative Language API" selected.]

**Add the key to your `.env` file:**

Open `agents/.env` (create it if it does not exist — use `agents/.env.example` as the template). Add the following line:

```
GOOGLE_API_KEY=AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

Replace the value with your actual key. Save the file.

**Verify `.gitignore` covers `.env`.** The `agents/.gitignore` file in the book's project already excludes `.env`. Confirm this by running:

```bash
cat agents/.gitignore | grep .env
```

If `.env` does not appear in the output, add the line `.env` to `agents/.gitignore` before doing anything else. An API key committed to a public repository will be detected by automated scanners within minutes and invalidated by Google — then you will need to create a new one.

---

## B.7 Step 4B — Create a Service Account (Option B — Required for BTP Deployment)

Follow these steps if you are setting up the service account now. If you are using Option A for the moment, you can skip to section B.8 and return here before Chapter 10.

**Create the service account:**

1. In the left navigation, click **IAM & Admin** > **Service Accounts**.
2. Click **+ Create Service Account** at the top.
3. Fill in the form:
   - **Service account name:** `msds-rag-agent`
   - **Service account ID:** This auto-fills as `msds-rag-agent`. Leave it.
   - **Description:** `Service account for MSDS hybrid RAG agent`
4. Click **Create and Continue**.

**Assign the role:**

On the next screen, you will grant this service account access to your project:

1. Click the **Select a role** dropdown.
2. Search for `Vertex AI User`.
3. Select **Vertex AI User** (it appears under the Vertex AI category).
4. Click **Continue**, then click **Done**.

The `Vertex AI User` role grants permission to call the Vertex AI and Generative Language APIs. It does not grant access to GCP storage, databases, or administrative functions — this follows the principle of least privilege.

[SCREENSHOT: Service account creation form showing the name "msds-rag-agent" and description. Second screenshot: IAM role selection showing "Vertex AI User" selected.]

**Download the JSON key:**

1. In the Service Accounts list, click the email address of the `msds-rag-agent` account.
2. Click the **Keys** tab.
3. Click **Add Key** > **Create new key**.
4. Select **JSON** format.
5. Click **Create**.

The browser downloads a file named something like `msds-hybrid-rag-423901-a1b2c3d4e5f6.json`. This file contains the private key for the service account.

[SCREENSHOT: Service account Keys tab showing the "Add Key" dropdown and JSON format selection. Second screenshot: the key download confirmation dialog.]

**Handle this file with care.**

The JSON key file is a credential with the same power as a password. Anyone who has this file can call the Vertex AI API on your account. Several rules apply:

- Do not rename or move the file into the repository directory. Keep it in a directory outside the project, such as `~/.gcp/keys/`.
- Do not commit it to git under any circumstances. There is no recovery if you push it to a public repository — invalidate the key immediately and create a new one.
- Do not put it in Dropbox, Google Drive, or any sync service unless that service uses encryption at rest that you control.
- Rotate the key (delete and re-create) if you believe it has been exposed.

A safe location on macOS or Linux:

```bash
mkdir -p ~/.gcp/keys
mv ~/Downloads/msds-hybrid-rag-*.json ~/.gcp/keys/msds-rag-agent.json
chmod 600 ~/.gcp/keys/msds-rag-agent.json
```

The `chmod 600` command makes the file readable only by your user account.

**Add the path to `.env`:**

```
GOOGLE_APPLICATION_CREDENTIALS=/Users/yourname/.gcp/keys/msds-rag-agent.json
```

Use the absolute path. The `~` shorthand does not always expand correctly in all contexts — use the full path.

When `GOOGLE_APPLICATION_CREDENTIALS` is set, the Google SDK uses it automatically. You do not need to call `genai.configure()` — the credentials are picked up from the environment.

---

## B.8 Step 5 — Test the Connection

Before closing the GCP console, verify that your credentials work. This test takes less than two minutes and eliminates an entire category of debugging later.

Create a temporary test file (do not put this inside the `agents/` directory — it is a throwaway):

```python
# test_gemini.py — delete after testing
import os
from dotenv import load_dotenv
import google.generativeai as genai

# Load your .env file
load_dotenv("agents/.env")

api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise ValueError("GOOGLE_API_KEY not set in agents/.env")

genai.configure(api_key=api_key)

model = genai.GenerativeModel("gemini-2.5-flash-preview-05-20")
response = model.generate_content("Say hello in one sentence.")
print(response.text)
```

Run it from the book's project root:

```bash
cd /path/to/book-agentic-hybrid-rag-on-btp
python test_gemini.py
```

Expected output (the exact wording varies):

```
Hello! It's wonderful to meet you.
```

Any short, grammatical sentence confirms that the API call succeeded, the key is valid, and the model is accessible from your machine.

**Common errors and their fixes:**

| Error message | Cause | Fix |
|---|---|---|
| `API key not valid. Please pass a valid API key.` | The key was not saved correctly in `.env`, or the `.env` path is wrong | Print `os.getenv("GOOGLE_API_KEY")` to confirm the value loads; check the path passed to `load_dotenv()` |
| `403 Generative Language API has not been used in project` | The API is not enabled | Return to section B.5 and enable it |
| `404 models/gemini-2.5-flash-preview-05-20 is not found` | The model name is wrong or not available in your region | Confirm the model name exactly — no extra spaces, correct hyphenation |
| `ModuleNotFoundError: No module named 'google.generativeai'` | Package not installed | Run `pip install google-generativeai python-dotenv` |

Delete `test_gemini.py` after the test succeeds.

---

## B.9 Step 6 — Understanding Free Tier and Costs

The GCP billing model for Generative AI is worth understanding before you run hundreds of API calls. Nothing in this book should surprise you with a large bill, but knowing the numbers builds confidence.

**text-embedding-004**

Embedding generation is priced per character of input. At the time of writing, `text-embedding-004` costs $0.000 per character on the free tier up to 1,500 requests per minute. For the MSDS demo, each PDF page produces one embedding call, and the ten sample documents in the project total roughly 80 pages. The total embedding cost is effectively zero.

Even at paid rates, `text-embedding-004` is one of the least expensive API calls available — well under $0.01 for the entire ingestion pipeline in this book.

**gemini-2.5-flash-preview-05-20**

Gemini 2.5 Flash is priced at approximately $0.075 per million input tokens and $0.30 per million output tokens for non-thinking responses. A typical MSDS query in this book sends about 2,000 input tokens (system prompt + retrieved context + question) and receives about 300 output tokens. That works out to roughly $0.00015 per query — fifteen hundredths of a cent.

Running the full demo pipeline one hundred times — which is more than enough to complete all chapters — costs under $0.02.

**The $300 credit**

GCP's $300 free credit expires after 90 days or when exhausted, whichever comes first. At the rates above, the credit is more than sufficient for the entire book plus several months of additional experimentation. The credit is not used for certain GCP services (compute quotas apply separately), but for the Vertex AI and Generative Language APIs, the credit applies in full.

**Monitoring spend**

To monitor your actual spend, go to **Billing** > **Reports** in the GCP Console. You can set a budget alert at **Billing** > **Budgets & alerts** to receive an email if you approach a threshold. Setting an alert at $5 is a sensible precaution that takes two minutes to configure.

![Vertex AI API overview and pricing page](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/gcp/01-vertex-ai-overview.png)

---

## B.10 Verification Checklist

Before returning to Chapter 2, confirm each of the following. Check them off in order — do not skip ahead if one item is unresolved.

- [ ] **GCP project created.** You have a project named `msds-hybrid-rag` (or your chosen name) and you have recorded the Project ID. The project appears when you click the project selector in the GCP Console.

- [ ] **Both APIs enabled.** Navigate to **APIs & Services** > **Enabled APIs & Services** and confirm that both "Generative Language API" and "Vertex AI API" appear in the list with an active status.

- [ ] **Credentials in place.** Either `GOOGLE_API_KEY` is set in `agents/.env` (Option A) or `GOOGLE_APPLICATION_CREDENTIALS` points to a valid JSON key file outside the repository directory (Option B). Not both — pick one for now.

- [ ] **`.env` excluded from git.** Run `git check-ignore -v agents/.env` from the project root. The output should confirm the file is ignored. If the command returns nothing (no output), the file is not ignored — add `.env` to `agents/.gitignore` immediately.

- [ ] **Test call succeeded.** You ran the Python test in section B.8 and received a valid sentence in response. The test file has been deleted.

If all five items are checked, your GCP environment is ready. Return to Chapter 2, section 3.4 to continue with the SAP BTP trial account setup.

---

> **Next step in Chapter 2.** After completing this appendix, the GCP portion of Chapter 2 (section 3.4) will be familiar. That section adds one more step not covered here: creating a **BTP Destination** that stores the GCP service account credentials so that the deployed application on BTP Cloud Foundry can call Vertex AI without embedding credentials in the application bundle. That step requires the service account JSON key from section B.7 — if you skipped Option B, you will need to complete it before Chapter 10.
