# Chapter 10: Deploying to SAP BTP Cloud Foundry

By the time you reach this chapter, you have a working Hybrid RAG system running locally against your BTP HANA Cloud trial. This chapter deploys it — unchanged code — to BTP Cloud Foundry. The FastAPI Python application becomes a CF app. The CAP Node.js service becomes an MTA module. HANA Cloud, already provisioned in Chapter 2, becomes the bound service.

Every configuration decision in this chapter has a specific rationale. Ports are dynamic because CF assigns them at container startup. Credentials come from service bindings because files cannot be trusted in a containerised environment. The two applications communicate over CF routes rather than localhost because they are separate containers on a distributed platform. Understanding these rationales means you can adapt the deployment pattern to other BTP applications, not just this one.

---

## 10.1 What Changes Between Local and BTP

Before touching a single deployment file, it is worth being precise about what is actually different in a Cloud Foundry environment. There are three categories of change, and understanding all three prevents most deployment failures.

**Ports are dynamic.** On your laptop, you choose the port. You run FastAPI on 8000 and CAP on 4004, and nothing conflicts. In Cloud Foundry, the platform assigns a port at container startup and communicates it through the `$PORT` environment variable. Your application must read that variable and bind to it. If it binds to a hardcoded port, it will start and immediately fail health checks. This is why the `manifest.yml` command is `uvicorn main:app --host 0.0.0.0 --port $PORT` rather than a fixed port number.

**Credentials come from service bindings, not files.** A `.env` file is a local development convenience. It is not a deployment artifact. On BTP, sensitive values — database credentials, API keys, GCP service account keys — are delivered to running containers through Cloud Foundry service bindings injected as JSON into the `VCAP_SERVICES` environment variable. The `GOOGLE_API_KEY` that worked locally never appears in a deployed container's filesystem or in `manifest.yml`. This is not just a best practice; it is how the platform is designed. The BTP Destination Service stores the Vertex AI credentials at runtime — the CAP service reads them from the Destination Service, never from environment variables visible in `cf env`.

**Inter-service communication uses the platform's routing layer.** On localhost, CAP reaches the Python agent at `http://localhost:8000`. On BTP Cloud Foundry, every application has a route — a public HTTPS URL managed by the platform's router. The two applications communicate over those routes. The BTP Destination Service provides a managed, centralised way to store and reference those URLs, so that changing the backend URL only requires updating one entry in the BTP Cockpit rather than redeploying every service that references it.

These three changes — dynamic ports, credential delivery via bindings, and HTTPS routing — account for almost all of the configuration work in this chapter.

---

## 10.2 Why Two Separate Applications

The system deploys as two independent CF applications: the FastAPI Python service and the CAP Node.js service. This is not an accident of how the code happens to be organised — it is a deliberate architectural choice with operational consequences.

FastAPI handles AI orchestration and HANA data access. It is a standard Python web service that runs on any CF Python buildpack. Its responsibilities are: receiving document upload requests, running the LangGraph ingestion pipeline, querying HANA for vector and Knowledge Graph retrieval, calling Vertex AI for LLM inference, and returning answers. None of these responsibilities have any dependency on OData, Fiori, or BTP security services.

CAP handles OData protocol, Fiori UI rendering, S/4HANA product master integration via API_PRODUCT_SRV, and BTP service bindings for XSUAA authentication and HANA schema management. It is the SAP-native layer. Its responsibilities are: serving the Fiori Elements UI, validating OData requests, managing document and attachment records in HANA, and proxying processing and query requests to the FastAPI backend.

Keeping them separate means you can update the AI model, the LangGraph orchestration logic, or the vector retrieval strategy without touching the CAP service — and vice versa. The HTTP contract between them (multipart POST to `/process-upload`, JSON POST to `/query`, GET to `/status/{materialNumber}`) is stable and narrow. Either side can be redeployed independently as long as that contract is respected.

---

## 10.3 Pre-Deployment Checklist

Deployment failures are much easier to debug when you can be certain your local environment is correctly configured before you start. Work through this checklist before executing any `cf push` or `mbt build` command.

**Cloud Foundry CLI.** Run `cf version`. You need version 8 or later. If the command is not found, install from the Cloud Foundry Foundation releases page or, on macOS, with `brew install cloudfoundry/tap/cf-cli@8`. Log in with `cf login -a https://api.cf.<your-region>.hana.ondemand.com` and target the correct org and space with `cf target -o <org> -s <space>`.

**MTA Build Tool.** The CAP service is deployed using the MultiTarget Application (MTA) model, which requires the `mbt` CLI. Run `mbt --version`. If it is missing, install with `npm install -g mbt`. This tool reads `mta.yaml`, builds all modules, and packages them into a single `.mtar` archive that the CF deployer can process.

**BTP Cloud Foundry space.** Confirm you are in the correct space with `cf target`. The space must have the SAP HANA Cloud instance accessible to it. If you are using a trial account, the HANA Cloud instance must be active — it stops automatically after 30 days of inactivity and must be restarted manually in the BTP Cockpit.

**HANA Cloud instance running.** In the BTP Cockpit, navigate to your subaccount, open the SAP HANA Cloud section, and confirm the instance status is "Running." Deployment will succeed even if HANA is stopped — the CAP service only attempts a database connection at runtime. But the smoke test in section 10.8 will fail until HANA is available.

**Google Cloud service account credentials.** The Python agent authenticates to Vertex AI using a Google Cloud service account. You should have a JSON key file from Chapter 2. For BTP deployment, this key is stored in the BTP Destination Service — never as a file in the container, never as a plain environment variable visible in `cf env`.

---

## 10.4 Step 1: Push the Python Agent

The Python agent deploys first because the CAP service needs to know its URL when configuring the Destination Service. Navigate to the `agents/` directory and examine the deployment manifest.

### Understanding manifest.yml

```yaml

---
applications:
  - name: hybrid-rag-agent
    buildpacks:
      - python_buildpack
    memory: 512M
    disk_quota: 1G
    instances: 1
    command: uvicorn main:app --host 0.0.0.0 --port $PORT
    path: .
    env:
      HANA_HOST:    ((hana-host))
      HANA_PORT:    "443"
      HANA_USER:    ((hana-user))
      HANA_PASSWORD: ((hana-password))
      GCP_PROJECT_ID: ((gcp-project-id))
      GCP_LOCATION:   us-central1
      LANGCHAIN_TRACING_V2: "true"
      LANGCHAIN_ENDPOINT:   "https://api.smith.langchain.com"
      LANGCHAIN_API_KEY:    ((langchain-api-key))
      PYTHONPATH: "."
```

Walk through each field:

`name: hybrid-rag-agent` sets the application name in Cloud Foundry. This becomes part of the default route: `hybrid-rag-agent.<your-cf-domain>`. Choose a name that is unique within your org.

`buildpacks: [python_buildpack]` tells Cloud Foundry which buildpack to use for detecting, compiling, and packaging the application. The Python buildpack reads `requirements.txt`, creates a virtualenv, installs dependencies, and configures the runtime. No Dockerfile is needed.

`memory: 512M` and `disk_quota: 1G` set the container resource limits. 512 MB is sufficient for the FastAPI server and the LangGraph agent under moderate load. The HANA Python driver (`hdbcli`), Vertex AI client libraries, and LangChain components together consume roughly 200-250 MB at startup. If you observe OOM kills in logs, increase to 1G.

`command: uvicorn main:app --host 0.0.0.0 --port $PORT` is the startup command. The `--host 0.0.0.0` binding is required — binding only to `127.0.0.1` means the platform's router cannot reach the container. The `$PORT` variable is provided by Cloud Foundry and will be a value like 8080 or 61002 depending on the container assignment. The Python buildpack expands this shell variable before executing the command.

`path: .` tells the CF CLI which directory to upload. Since you are running `cf push` from within `agents/`, the `.` means the entire agents directory is packaged and sent to the staging container.

`PYTHONPATH: "."` ensures that Python can find modules in the application root. Without this, relative imports within the agent codebase will fail at runtime.

The `((variable))` syntax in the env block are placeholders — the real values are supplied through `cf set-env` commands or a User-Provided Service, covered in the next step. If you pushed this manifest as-is, the literal placeholder strings would appear as environment variable values, causing immediate connection failures at runtime.

### HANA connection in CF

In the deployed environment, HANA credentials come from `VCAP_SERVICES` via service binding — the same mechanism CAP uses. The `hdb_srv.py` module already handles this: it reads `VCAP_SERVICES` if direct environment variables are not set. No code change is needed to move from local `.env` file credentials to CF service binding credentials. The credential source changes; the application code does not.

### Pushing the application

From the `agents/` directory:

```bash
cf push hybrid-rag-agent --no-start
```

The `--no-start` flag stages the application — uploads the code, runs the buildpack, creates the container — but does not start it. This is important because the environment variables have not been set yet. Starting now would produce a crash-loop of failed HANA connections.

Confirm staging succeeded:

```bash
cf app hybrid-rag-agent
```

You should see the application in a `stopped` state with a route assigned. Note the route URL — something like `hybrid-rag-agent.cfapps.eu10.hana.ondemand.com`. You will need this URL when configuring the Destination Service.

---

## 10.5 Step 2: Create the User-Provided Service for Credentials

Cloud Foundry User-Provided Services (UPS) are the correct mechanism for delivering credentials to applications that need values which are not available through a managed service binding. Instead of setting individual environment variables one by one on each application, you define a named service with a JSON payload of key-value pairs, bind it to any application that needs those values, and Cloud Foundry delivers the entire payload via `VCAP_SERVICES`.

The security rationale is straightforward. If you set credentials with `cf set-env`, they are visible in `cf env <app>` to anyone with developer access to the space. If you put credentials in `manifest.yml`, they will eventually end up in version control. A User-Provided Service stores the values in Cloud Foundry's internal credential store, not in any file that exists in your repository.

Create the service with the actual values for your environment:

```bash
cf cups hybrid-rag-agent-env -p '{
  "HANA_HOST": "your-hana-instance.hanacloud.ondemand.com",
  "HANA_PORT": "443",
  "HANA_USER": "DBADMIN",
  "HANA_PASSWORD": "your-database-password",
  "GCP_PROJECT_ID": "your-gcp-project-id",
  "GCP_LOCATION": "us-central1",
  "LANGCHAIN_API_KEY": "your-langchain-api-key"
}'
```

`cf cups` stands for `cf create-user-provided-service`. The `-p` flag accepts a JSON string of parameters.

Now bind the service to the application:

```bash
cf bind-service hybrid-rag-agent hybrid-rag-agent-env
```

Cloud Foundry will inject the key-value pairs from this service into the `VCAP_SERVICES` JSON available to the container. The `HANA_HOST` key in the UPS becomes the `HANA_HOST` environment variable in the application container.

If you need to update the credentials later — for example, to rotate the HANA password — you can use:

```bash
cf uups hybrid-rag-agent-env -p '{"HANA_PASSWORD": "new-password"}'
cf restart hybrid-rag-agent
```

The `cf uups` command (`update-user-provided-service`) replaces the entire parameter set, so include all keys, not just the changed one.

Now start the application:

```bash
cf start hybrid-rag-agent
```

Watch the startup logs:

```bash
cf logs hybrid-rag-agent --recent
```

A successful startup will show uvicorn reporting that it is listening on the assigned port. A failed startup will show a Python traceback — usually a missing environment variable or an import error from a missing package. The most common first failure is a missing `google-cloud-aiplatform` package because it was not in `requirements.txt`. Confirm your `requirements.txt` includes every library imported anywhere in the codebase.

Verify the agent is reachable:

```bash
curl https://hybrid-rag-agent.<your-cf-domain>/health
```

You should receive a JSON response indicating the service status and confirming that the HANA and Vertex AI connections are available.

---

## 10.6 Step 3: Build and Deploy the CAP Service

The CAP service is deployed using the MTA (MultiTarget Application) model rather than a direct `cf push`. MTA is an SAP-developed open standard for describing multi-component applications — a single `mta.yaml` file describes every module (CAP service, Python service), every service binding (HANA, UPS), and every dependency between them. The `mbt build` tool compiles all modules and packages them, and the CF MTA deployer (`cf deploy`) orchestrates the deployment.

Examine the MTA descriptor:

```yaml
_schema-version: "3.3.0"
ID: msds-hybrid-rag
version: 1.0.0
description: Hybrid RAG MSDS system on SAP BTP

modules:
  - name: hybrid-rag-agent
    type: python
    path: agents
    build-parameters:
      builder: custom
      commands:
        - pip install -r requirements.txt
    parameters:
      memory: 512M
      disk-quota: 1G
    properties:
      PYTHONPATH: "."
    requires:
      - name: hybrid-rag-agent-env

  - name: msds-hybrid-rag-cap
    type: nodejs
    path: cap-srv
    build-parameters:
      builder: npm
      build-result: gen/srv
    parameters:
      memory: 256M
      disk-quota: 512M
    properties:
      AGENT_URL: "~{hybrid-rag-agent/url}"
    requires:
      - name: msds-hybrid-rag-hana
      - name: hybrid-rag-agent-env
    provides:
      - name: cap-srv-api
        properties:
          url: ${default-url}

resources:
  - name: msds-hybrid-rag-hana
    type: com.sap.xs.hana-schema
    parameters:
      service: hana
      service-plan: schema

  - name: hybrid-rag-agent-env
    type: org.cloudfoundry.user-provided-service
```

Several lines require explanation.

`AGENT_URL: "~{hybrid-rag-agent/url}"` is an MTA cross-reference. The `~{}` syntax means "substitute the value of this property from another module at deployment time." The `hybrid-rag-agent` module, when deployed, exposes its assigned route URL as the `url` property. The CAP module reads that URL and stores it in its own `AGENT_URL` environment variable. This eliminates hardcoding: even if the Python service is redeployed to a different route, the CAP service will be updated automatically on the next deployment.

`build-result: gen/srv` tells the MTA deployer where to find the compiled CAP artifacts after the npm build. The `cds build` command, which runs as part of `npm run build`, compiles CDS models, generates the OData metadata, and writes the production-ready service files to `gen/srv`. The MTA deployer packages only this directory, not the entire `cap-srv` source tree.

`type: com.sap.xs.hana-schema` declares that the deployer should create (or reuse) a HANA schema resource. This becomes a service binding in Cloud Foundry: the CAP service's `VCAP_SERVICES` will contain the HANA connection details, and the `@cap-js/hana` plugin will read them automatically. You do not configure a connection string in the CAP application; the binding provides it.

`type: org.cloudfoundry.user-provided-service` in the resources section tells the MTA deployer that `hybrid-rag-agent-env` is an existing UPS that should be bound but not created. The UPS you created in step 10.5 is referenced here by name. Both the Python agent and the CAP service are bound to it, which is how both processes receive the HANA credentials.

### Running the build

From the `cap-srv/` directory (or the repo root, depending on where `mta.yaml` lives):

```bash
mbt build
```

This command reads `mta.yaml`, executes the build commands for each module, and produces an `.mtar` archive in the `mta_archives/` directory. The archive is a standard ZIP containing all compiled artifacts for every module.

If the build fails at the `cds build` step, the most common cause is a CDS syntax error or a missing npm dependency. Run `npm run build` in the `cap-srv/` directory directly to see the full CDS compiler output.

### Deploying the MTA

Install the CF MTA plugin if you have not already:

```bash
cf install-plugin multiapps
```

Deploy the built archive:

```bash
cf deploy mta_archives/msds-hybrid-rag_1.0.0.mtar
```

The deployer will work through a sequence of operations: creating or updating service instances, uploading application binaries, binding services, and starting applications. This takes two to five minutes. The terminal output shows each step with a status indicator. If any step fails, the deployer stops and shows the error. Common failures at this stage are HANA schema creation failures (usually a quota issue on a trial account) and npm install failures caused by package resolution errors.

When the deployment completes, both applications will be running. Confirm with:

```bash
cf apps
```

You should see `hybrid-rag-agent` and `msds-hybrid-rag-cap` both in a `started` state with routes assigned.

---

## 10.7 Step 4: Configure the BTP Destination for Vertex AI

In local development, Vertex AI credentials live in your `.env` file as `GOOGLE_APPLICATION_CREDENTIALS` pointing to a local JSON key file. That pattern does not belong in a deployed environment — a JSON key file in a container filesystem is one restart away from being lost, and it is visible to anyone with container access.

In BTP Cloud Foundry, the Vertex AI credentials are stored in the BTP Destination Service. The Destination Service is the enterprise credential management pattern across the entire BTP portfolio — the same mechanism used for S/4HANA connectivity, external REST APIs, and OAuth token exchange. The CAP service reads the Vertex AI credentials from the Destination Service at runtime. They are never stored in the app container, never in environment variables visible in `cf env`, and never in any file that could be accidentally committed or shared.

The production pattern in the CAP service handler, instead of reading from environment variables directly, uses the SAP Cloud SDK's destination resolution:

```javascript
const { executeHttpRequest } = require('@sap-cloud-sdk/http-client');
const response = await executeHttpRequest(
  { destinationName: process.env.BACKEND_DESTINATION },
  { method: 'POST', url: '/query', data: body }
);
```

The `executeHttpRequest` function handles destination resolution, certificate verification, and — when configured — token propagation. This is the mature BTP application pattern. For the current deployment, we configure the Destination Service so it is available when you move to production hardening in a later chapter.

### Creating the agent backend destination

Navigate to your BTP subaccount in the BTP Cockpit. Select **Connectivity** from the left navigation, then **Destinations**. Click **New Destination** and fill in the following values:

- **Name:** `hybrid-rag-agent`
- **Type:** HTTP
- **URL:** `https://hybrid-rag-agent.<your-cf-domain>` (the route from step 10.4)
- **Proxy Type:** Internet
- **Authentication:** NoAuthentication

Save the destination. You can test it immediately by clicking **Check Connection** — the cockpit will send a GET request to the root URL of the agent and report the HTTP response code.

### Creating the Vertex AI destination

Click **New Destination** again and configure the Vertex AI credentials:

- **Name:** `VertexAI`
- **Type:** HTTP
- **URL:** `https://us-central1-aiplatform.googleapis.com`
- **Proxy Type:** Internet
- **Authentication:** NoAuthentication

Add additional properties:

| Property | Value |
|----------|-------|
| `gcp.project_id` | Your GCP project ID |
| `gcp.location` | `us-central1` |
| `gcp.service_account_key` | The entire contents of your `gcp-sa-key.json` file |

BTP encrypts the `gcp.service_account_key` value at rest. The service account JSON key is now stored in one place — the BTP Destination Service — and accessible to any BTP application in this subaccount that needs Vertex AI access. Rotating the credentials means updating this one destination entry, not redeploying any application.

---

## 10.8 Step 5: Load the Ontology

The HANA Knowledge Graph requires the MSDS ontology to be loaded before any queries can run against it. In local development this was done by calling the admin endpoint directly. In the deployed environment, the process is identical, but the URL is the deployed agent route rather than localhost.

Obtain the agent route:

```bash
cf app hybrid-rag-agent | grep routes
```

Load the ontology:

```bash
curl -X POST \
  https://hybrid-rag-agent.<your-cf-domain>/admin/load-ontology \
  -H "Content-Type: application/json"
```

This endpoint triggers the same ontology loading logic from Chapter 4 — parsing the RDF Turtle file and inserting the triples into HANA's graph store. On the first deployment, this will take 15-30 seconds depending on the size of the ontology. Subsequent calls are idempotent: the endpoint checks whether the graph already exists before attempting to insert.

If the call returns a 500 error, the most likely cause is a HANA connection failure. Check the agent logs:

```bash
cf logs hybrid-rag-agent --recent
```

Look for a `hdbcli` connection error. If you see "authentication failed," confirm the `HANA_USER` and `HANA_PASSWORD` values in the User-Provided Service. If you see "host not found," confirm the `HANA_HOST` value. Note that HANA Cloud hostnames are long strings in the format `<uuid>.hana.ondemand.com` — confirm there are no trailing spaces or missing characters.

---

## 10.9 Step 6: Smoke Test the Deployed System

With both services running and the ontology loaded, run through each integration point systematically before calling the deployment complete.

### Agent health endpoint

```bash
curl https://hybrid-rag-agent.<your-cf-domain>/health
```

Expected response: a JSON object confirming service status, HANA connectivity, and Vertex AI availability. If HANA shows as unreachable, the agent will still start and respond on the health endpoint — it will report the connection failure in the status fields rather than refusing to respond.

### Direct query to the agent

```bash
curl -X POST \
  https://hybrid-rag-agent.<your-cf-domain>/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What documents are available for material MAT-001?", "session_id": "smoke-test-01"}'
```

This bypasses the CAP layer entirely and tests the LangGraph agent directly against HANA. The question validates the end-to-end flow: the agent queries both the Knowledge Graph and the vector store, calls Vertex AI for answer synthesis, and returns the result. You should receive a JSON response with an `answer` field and a `retrieval_path` field indicating which chains were invoked. If this succeeds, the HANA connection, the Vertex AI embedding model, and the LangGraph orchestration are all functional in the deployed environment.

### CAP OData endpoint

```bash
curl https://msds-hybrid-rag-cap.<your-cf-domain>/odata/v4/documents/Documents
```

This calls the CAP OData service's Documents entity set. On a fresh deployment, the response will be an empty array `{"value": []}` — no documents have been uploaded yet. An empty array is a successful response; a 500 error indicates a CAP startup or HANA binding problem.

### Fiori Elements UI

Open the CAP application URL in a browser:

```
https://msds-hybrid-rag-cap.<your-cf-domain>/index.html
```

The Fiori Elements list report should render. If you see a blank page, open the browser developer tools and check the network tab for 401 or 403 errors — these indicate an XSUAA configuration issue. For a non-XSUAA deployment (no authentication configured), the UI should load without any login screen.

---

## 10.10 Troubleshooting

Deployment failures follow predictable patterns. The following are the most common failure modes and their resolution paths.

### Memory quota exceeded

**Symptom:** Application crashes shortly after startup. Logs show `Signal 9 (SIGKILL)` or the application disappears from `cf apps` with a restart count incrementing.

**Cause:** The container exceeded its memory limit. The Python buildpack allocates the full 512M during startup as the HANA driver, LangChain, and Vertex AI libraries load. If additional packages were added after the memory limit was set, startup memory may now exceed the limit.

**Resolution:** Increase the memory limit in `manifest.yml` to `1G` and repush, or use `cf scale hybrid-rag-agent -m 1G` to update the limit without repushing.

### HANA connection refused

**Symptom:** Agent starts successfully but `/health` reports HANA as unreachable. Logs show `[HDB][ERR] authentication failed` or `[HDB][ERR] connection refused`.

**Cause:** Incorrect credentials in the User-Provided Service, or the HANA Cloud instance is stopped.

**Resolution:** Verify the UPS values with `cf env hybrid-rag-agent` (look for `VCAP_SERVICES` in the output and find the `hybrid-rag-agent-env` entry). Compare the `HANA_HOST` value against the hostname shown in the BTP Cockpit HANA Cloud manager. If the instance is stopped, start it from the BTP Cockpit and wait two to three minutes before retrying.

### GCP authentication failure

**Symptom:** Queries fail with a `google.api_core.exceptions.PermissionDenied` error in the agent logs.

**Cause:** The GCP service account credentials are not correctly configured, or the service account does not have the required Vertex AI roles.

**Resolution:** Confirm that `GCP_PROJECT_ID` in the UPS matches the project where Vertex AI is enabled. Confirm the Vertex AI Destination in BTP has the correct `gcp.service_account_key` value. Confirm the service account has the Vertex AI User role in GCP IAM. If you are using a key file directly, base64-encode the JSON content and set it as an environment variable, then decode it to a temp file at startup in the application's entry point.

### CAP cannot reach agent

**Symptom:** The Fiori UI loads but queries return an error. CAP logs show `ECONNREFUSED` or `ENOTFOUND` when calling the agent URL.

**Cause:** The `AGENT_URL` environment variable in the CAP service contains an incorrect value, or the Python agent is not running.

**Resolution:** Check `cf env msds-hybrid-rag-cap` and confirm the `AGENT_URL` value is the correct HTTPS route for the Python agent. Confirm the Python agent is running with `cf app hybrid-rag-agent`. If you recently redeployed the Python agent and its route changed, update the destination in the BTP Cockpit and use `cf set-env` to update the `AGENT_URL` value on the CAP service, then restart it.

### Package not found during staging

**Symptom:** The `cf push` command fails during the staging phase with a `pip install` error.

**Cause:** A package in `requirements.txt` is either misspelled, unavailable at the specified version, or requires a system library that is not present in the Cloud Foundry container.

**Resolution:** Read the full staging log carefully — the package name and the error message from pip are usually clear. For packages that require compiled C extensions (such as `hdbcli`), confirm that a pre-compiled wheel is available for the Python version used by the buildpack. You can pin the Python version in a `runtime.txt` file at the root of the `agents/` directory with content `python-3.11.x`.

---

## 10.11 Scaling

The system as deployed runs as single instances of each service. For a pilot with a handful of users, this is sufficient. For broader use, both the Python agent and the CAP service can be scaled horizontally — adding more container instances that share the incoming request load behind the Cloud Foundry router.

Scale the Python agent to two instances:

```bash
cf scale hybrid-rag-agent -i 2
```

Scale the CAP service:

```bash
cf scale msds-hybrid-rag-cap -i 2
```

Cloud Foundry's built-in router distributes requests across instances using round-robin by default. Because the Python agent is stateless — the LangGraph agent state is not persisted between requests, and HANA handles all persistent state — horizontal scaling requires no additional configuration. Each instance handles requests independently.

There are two situations where single-instance deployment is the correct choice even at higher load. First, during active development: when you are pushing frequent updates, having multiple instances means you need to track whether all instances have restarted to the new version. Second, during debugging: multiple instances produce interleaved log streams that can be difficult to read with `cf logs`. For debugging, scale to one instance, reproduce the problem, then scale back up.

Memory scaling — increasing the memory limit per instance — is more relevant for the Python agent than instance scaling. The LangGraph execution model creates new graph instances per request; large numbers of concurrent requests will increase memory pressure faster than CPU pressure. If you observe slow response times under load, check the memory usage with `cf app hybrid-rag-agent` before adding instances. A single 2G instance is often more cost-effective than two 512M instances for a memory-bound workload.

For production deployments with SLA requirements, consider enabling autoscaling through the Application Autoscaler service available in the BTP Service Marketplace. It can scale instances based on CPU, memory, or custom metrics, and scale them back down during quiet periods to control costs.

---

## 10.12 What You Have Built

You have deployed a production-grade Material Document Intelligence Platform to SAP BTP Cloud Foundry. Any PDF document — MSDS, invoice, batch certificate, inspection report, maintenance manual, legal filing — can be uploaded against a SAP Material Number, processed into a vector store and Knowledge Graph, and queried in natural language. The system runs on SAP's enterprise cloud platform, uses SAP HANA Cloud for both AI storage layers, integrates with real S/4HANA product master data via API_PRODUCT_SRV, and presents a familiar Fiori Elements interface.

Two applications are running as Cloud Foundry containers. The Python FastAPI service — `hybrid-rag-agent` — runs a LangGraph agent that dispatches every incoming question to parallel retrieval chains: a SPARQL chain that queries the HANA RDF Knowledge Graph for structured facts, and a vector similarity chain that searches HANA's vector index for semantically relevant passages. The agent synthesises the results using a Gemini model on Google Vertex AI and returns a grounded answer with a traceable retrieval path.

The CAP Node.js service — `msds-hybrid-rag-cap` — hosts an OData V4 API, a Fiori Elements UI, and an attachment handling layer. It validates material numbers against S/4HANA product master data, manages document records in HANA, and proxies processing and query requests to the FastAPI backend. Credentials for Vertex AI are stored in the BTP Destination Service — never in application code, never in deployment files.

This is the foundation for an enterprise AI capability that can scale across your SAP landscape. The same platform, the same patterns, the same HANA instance that stores your vector embeddings and Knowledge Graph triples — extended to handle every document type your organisation processes against SAP materials.

---

## 10.13 Chapter Checkpoint

Work through this list before moving to the next chapter. Each item verifies a specific part of the deployed system.

- `cf app hybrid-rag-agent` shows the application in `started` state with a route assigned. (Section 10.4)
- `curl https://hybrid-rag-agent.<domain>/health` returns a JSON response with no error fields. (Section 10.9)
- The User-Provided Service `hybrid-rag-agent-env` exists and is bound to both applications. (Section 10.5)
- `cf deploy` completed without errors and both applications appear in `cf apps`. (Section 10.6)
- A BTP Destination named `hybrid-rag-agent` exists in the subaccount, pointing to the Python agent URL. (Section 10.7)
- A BTP Destination named `VertexAI` exists with the GCP service account key stored as a destination property. (Section 10.7)
- `curl -X POST .../admin/load-ontology` returned a 200 status code. (Section 10.8)
- A direct `curl` POST to `/query` with question "What documents are available for material MAT-001?" returns an answer with a retrieval path. (Section 10.9)
- The Fiori Elements UI loads at the CAP application URL without errors in the browser console. (Section 10.9)

If every item on this list is green, the system is deployed and functional. The next chapter addresses operational concerns — observability, performance tuning, and the integration patterns that allow this system to participate in broader SAP workflows.
