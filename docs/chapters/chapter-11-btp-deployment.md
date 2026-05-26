# Chapter 11: Deploying to SAP BTP Cloud Foundry

There is a gap that every developer eventually has to cross, and it is almost always wider than expected. On one side: a working system on your laptop. On the other: that same system running reliably in the cloud, handling real traffic, connected to real data, and accessible to real users. The code on both sides is the same. Everything else is different.

For the system built in this book, the gap has a specific shape. You have a Python FastAPI service managing a LangGraph agent that talks to SAP HANA Cloud and Google Vertex AI. You have a CAP Node.js service hosting the Fiori UI and the OData V4 API. On your laptop, these two processes communicate over `localhost`. Credentials live in a `.env` file. The port is fixed. None of that survives contact with SAP BTP Cloud Foundry.

This chapter is about crossing that gap. We will work through each step in the order you would actually execute it: getting your credentials out of environment files and into services, pushing the Python agent, building and deploying the CAP application, wiring the two together through the BTP Destination Service, loading the knowledge graph, and verifying that the deployed system actually works. By the end, you will have a production-grade deployment on BTP Cloud Foundry — and you will understand why every configuration decision was made the way it was.

---

## 11.1 What Changes Between Local and BTP

Before touching a single deployment file, it is worth being precise about what is actually different in a Cloud Foundry environment. There are three categories of change, and understanding all three prevents most deployment failures.

**Ports are dynamic.** On your laptop, you choose the port. You run FastAPI on 8000 and CAP on 4004, and nothing conflicts. In Cloud Foundry, the platform assigns a port at container startup and communicates it through the `$PORT` environment variable. Your application must read that variable and bind to it. If it binds to a hardcoded port, it will start and immediately fail health checks. This is why the `manifest.yml` command is `uvicorn main:app --host 0.0.0.0 --port $PORT` rather than a fixed port number.

**Credentials come from service bindings, not files.** A `.env` file is a local development convenience. It is not a deployment artifact. On BTP, sensitive values — database credentials, API keys, service account keys — are delivered to running containers through two mechanisms: environment variables set on the application, and Cloud Foundry service bindings injected as JSON into the `VCAP_SERVICES` environment variable. Neither mechanism involves a file on disk that could be accidentally committed or copied. This is not just a best practice; it is how the platform is designed.

**Inter-service communication uses the platform's routing layer.** On localhost, CAP reaches the Python agent at `http://localhost:8000`. On BTP Cloud Foundry, every application has a route — a public URL managed by the platform's router. Services communicate over those routes, not over `localhost`. The BTP Destination Service provides a managed, centralized way to store and reference those URLs, so that changing the backend URL only requires updating one entry in the BTP Cockpit rather than redeploying every service that references it.

These three changes — dynamic ports, credential delivery, and routing — account for almost all of the configuration work in this chapter. Everything else is build tooling.

---

## 11.2 Pre-Deployment Checklist

Deployment failures are much easier to debug when you can be certain your local environment is correctly configured before you start. Work through this checklist before executing any `cf push` or `mbt build` command.

**Cloud Foundry CLI.** Run `cf version`. You need version 8 or later. If the command is not found, install from the Cloud Foundry Foundation releases page or, on macOS, with `brew install cloudfoundry/tap/cf-cli@8`. Log in with `cf login -a https://api.cf.<your-region>.hana.ondemand.com` and target the correct org and space with `cf target -o <org> -s <space>`.

**MTA Build Tool.** The CAP service is deployed using the MultiTarget Application (MTA) model, which requires the `mbt` CLI. Run `mbt --version`. If it is missing, install with `npm install -g mbt`. This tool reads `mta.yaml`, builds all modules, and packages them into a single `.mtar` archive that the CF deployer can process.

**BTP Cloud Foundry space.** Confirm you are in the correct space with `cf target`. The space must have the SAP HANA Cloud instance bound to it. If you are using a trial account, the HANA Cloud instance must be active — it stops automatically after 30 days of inactivity and must be restarted manually in the BTP Cockpit.

**HANA Cloud instance running.** In the BTP Cockpit, navigate to your subaccount, open the SAP HANA Cloud section, and confirm the instance status is "Running." Deployment will succeed even if HANA is stopped — the CAP service only attempts a database connection at runtime. But the smoke test in section 11.9 will fail until HANA is available.

**Google Cloud service account credentials.** The Python agent authenticates to Vertex AI using a Google Cloud service account. You should have a JSON key file from Chapter 3. For BTP deployment, this key needs to be available to the agent container at runtime. The approach in this chapter stores it as an environment variable (base64-encoded) delivered through a User-Provided Service. Have the key file path ready.

**LangChain API key (optional).** If you enabled LangSmith tracing in Chapter 8, you need a LangChain API key. If you are deploying without tracing, set `LANGCHAIN_TRACING_V2` to `"false"` in the manifest. Tracing is strongly recommended for production systems but is not required for the deployment to function.

---

## 11.3 Step 1: Push the Python Agent

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

The `((variable))` syntax deserves its own explanation. This notation is *not* a feature of Cloud Foundry manifest files in general. It is a CredHub variable reference used by the CF deployer when working with CredHub-backed secrets, or it can be treated as a placeholder indicating "do not put the real value here." In this project, it signals that these values must be supplied through other means — specifically through `cf set-env` commands or User-Provided Services, which are covered in the next step. If you were to push this manifest as-is, the literal string `((hana-host))` would appear as the `HANA_HOST` environment variable, which is harmless from a security standpoint but would immediately cause a connection failure at runtime.

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

You should see the application in a `stopped` state with a route assigned. Note the route URL — something like `hybrid-rag-agent.cfapps.eu10.hana.ondemand.com`. You will need this URL when configuring the Destination Service in step 11.6.

---

## 11.4 Step 2: Create the User-Provided Service for Credentials

Cloud Foundry User-Provided Services (UPS) are the correct mechanism for delivering credentials to applications that need values which are not available through a managed service binding. Instead of setting individual environment variables one by one on each application, you define a named service with a JSON payload of key-value pairs, bind it to any application that needs those values, and Cloud Foundry delivers the entire payload via `VCAP_SERVICES`.

The security rationale is straightforward. If you set credentials with `cf set-env`, they are visible in `cf env <app>` to anyone with developer access to the space — which is sometimes acceptable but can lead to accidental exposure in screenshots, logs, or CI pipelines. If you put credentials in `manifest.yml`, they will eventually end up in version control. A User-Provided Service stores the values in Cloud Foundry's internal credential store, not in any file that exists in your repository.

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

Cloud Foundry will inject the key-value pairs from this service into the `VCAP_SERVICES` JSON available to the container. However, the FastAPI application reads these values as environment variables directly — not by parsing `VCAP_SERVICES`. This works because Cloud Foundry automatically promotes the parameters from a User-Provided Service into the application's environment when the service is bound. The `HANA_HOST` key in the UPS becomes the `HANA_HOST` environment variable in the application container.

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

## 11.5 Step 3: Build and Deploy the CAP Service

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

`type: org.cloudfoundry.user-provided-service` in the resources section tells the MTA deployer that `hybrid-rag-agent-env` is an existing UPS that should be bound but not created. The UPS you created in step 11.4 is referenced here by name. Both the Python agent and the CAP service are bound to it, which is how both processes receive the HANA credentials.

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

## 11.6 Step 4: Configure the BTP Destination

The BTP Destination Service provides a centralized configuration layer for HTTP connections between services in a BTP subaccount. Instead of hardcoding the Python agent URL in the CAP application, the CAP service stores only a destination name and asks the Destination Service to resolve it to an actual URL at request time. This indirection is valuable in production: you can update the backend URL in one place — the BTP Cockpit — without redeploying the CAP service.

In the architecture of this book, the Destination Service is the mechanism that replaces `localhost:8000`. The CAP service's `AGENT_URL` environment variable is used in local development, but in a full production deployment the cleaner approach — and the one used by mature BTP applications — is to read a destination name from an environment variable and use the SAP Cloud SDK's `executeHttpRequest()` function to resolve and call it.

That production pattern looks like this. In the CAP service handler, instead of:

```javascript
const response = await axios.post(`${process.env.AGENT_URL}/query`, body);
```

you use:

```javascript
const { executeHttpRequest } = require('@sap-cloud-sdk/http-client');
const response = await executeHttpRequest(
  { destinationName: process.env.BACKEND_DESTINATION },
  { method: 'POST', url: '/query', data: body }
);
```

The `executeHttpRequest` function handles destination resolution, certificate verification, and — when configured — token propagation. For the current deployment, we use the simpler approach of passing the agent URL directly as `AGENT_URL`, but understanding the destination pattern is important for production hardening.

### Creating the destination

To support the destination pattern (and as a best practice for knowing where your backend lives), create a destination in the BTP Cockpit even if the CAP service is currently using `AGENT_URL` directly.

Navigate to your BTP subaccount in the BTP Cockpit. Select **Connectivity** from the left navigation, then **Destinations**. Click **New Destination** and fill in the following values:

- **Name:** `hybrid-rag-agent`
- **Type:** HTTP
- **URL:** `https://hybrid-rag-agent.<your-cf-domain>` (the route from step 11.3)
- **Proxy Type:** Internet
- **Authentication:** NoAuthentication

The authentication type is NoAuthentication because the Python agent does not have its own authentication mechanism — it relies on the CAP layer above it to handle XSUAA tokens, and its HANA connection uses the credentials delivered through the UPS. If you later add API key authentication to the Python service, update this destination to use `ClientCertificateAuthentication` or `BasicAuthentication` accordingly.

Save the destination. You can test it immediately by clicking **Check Connection** — the cockpit will send a GET request to the root URL of the agent and report the HTTP response code.

---

## 11.7 Step 5: Load the Ontology

The HANA knowledge graph requires the MSDS ontology to be loaded before any queries can run against it. In local development this was done by calling the admin endpoint directly. In the deployed environment, the process is identical, but the URL is the deployed agent route rather than localhost.

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

This endpoint triggers the same ontology loading logic from Chapter 5 — parsing the RDF Turtle file and inserting the triples into HANA's graph store. On the first deployment, this will take 15-30 seconds depending on the size of the ontology. Subsequent calls are idempotent: the endpoint checks whether the graph already exists before attempting to insert.

If the call returns a 500 error, the most likely cause is a HANA connection failure. Check the agent logs:

```bash
cf logs hybrid-rag-agent --recent
```

Look for a `hdbcli` connection error. If you see "authentication failed," confirm the `HANA_USER` and `HANA_PASSWORD` values in the User-Provided Service. If you see "host not found," confirm the `HANA_HOST` value. Note that HANA Cloud hostnames are long strings in the format `<uuid>.hana.ondemand.com` — confirm there are no trailing spaces or missing characters.

---

## 11.8 Step 6: Smoke Test the Deployed System

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
  -d '{"question": "What is the flash point of acetone?", "session_id": "smoke-test-01"}'
```

This bypasses the CAP layer entirely and tests the LangGraph agent directly. You should receive a JSON response with an `answer` field and a `retrieval_path` field indicating which chains were invoked. If this succeeds, the HANA connection, the Vertex AI embedding model, and the LangGraph orchestration are all functional.

### CAP OData endpoint

```bash
curl https://msds-hybrid-rag-cap.<your-cf-domain>/odata/v4/MSDSService/Materials
```

This calls the CAP OData service's Materials entity set. On a fresh deployment, the response will be an empty array `{"value": []}` — no materials have been uploaded yet. An empty array is a successful response; a 500 error indicates a CAP startup or HANA binding problem.

### Fiori Elements UI

Open the CAP application URL in a browser:

```
https://msds-hybrid-rag-cap.<your-cf-domain>/index.html
```

The Fiori Elements list report should render. If you see a blank page, open the browser developer tools and check the network tab for 401 or 403 errors — these indicate an XSUAA configuration issue. For a non-XSUAA deployment (no authentication configured), the UI should load without any login screen.

---

## 11.9 Troubleshooting

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

**Resolution:** Confirm that `GCP_PROJECT_ID` in the UPS matches the project where Vertex AI is enabled. The Python agent uses Application Default Credentials — in a Cloud Foundry container, this requires either a service account key in the `GOOGLE_APPLICATION_CREDENTIALS` environment variable or the Workload Identity Federation configuration from Chapter 3. If you are using a key file, base64-encode the JSON content and set it as an environment variable, then decode it to a temp file at startup in the application's entry point.

### CAP cannot reach agent

**Symptom:** The Fiori UI loads but queries return an error. CAP logs show `ECONNREFUSED` or `ENOTFOUND` when calling the agent URL.

**Cause:** The `AGENT_URL` environment variable in the CAP service contains an incorrect value, or the Python agent is not running.

**Resolution:** Check `cf env msds-hybrid-rag-cap` and confirm the `AGENT_URL` value is the correct HTTPS route for the Python agent. Confirm the Python agent is running with `cf app hybrid-rag-agent`. If you recently redeployed the Python agent and its route changed, update the destination in the BTP Cockpit and, if using `AGENT_URL` directly, use `cf set-env` to update the value and restart the CAP service.

### Package not found during staging

**Symptom:** The `cf push` command fails during the staging phase with a `pip install` error.

**Cause:** A package in `requirements.txt` is either misspelled, unavailable at the specified version, or requires a system library that is not present in the Cloud Foundry container.

**Resolution:** Read the full staging log carefully — the package name and the error message from pip are usually clear. For packages that require compiled C extensions (such as `hdbcli`), confirm that a pre-compiled wheel is available for the Python version used by the buildpack. You can pin the Python version in a `runtime.txt` file at the root of the `agents/` directory with content `python-3.11.x`.

---

## 11.10 Scaling

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

## 11.11 What You Have Built

Step back and look at what is now running in SAP BTP Cloud Foundry.

Two applications are deployed as Cloud Foundry containers. The Python FastAPI service — `hybrid-rag-agent` — is running a LangGraph agent that dispatches every incoming question to parallel retrieval chains: a SPARQL chain that queries the HANA RDF knowledge graph for structured facts, and a vector similarity chain that searches HANA's `L2_DISTANCE` index for semantically relevant passages. The agent synthesizes the results using a Gemini model on Google Vertex AI and returns a grounded answer with a traceable retrieval path.

The CAP Node.js service — `msds-hybrid-rag-cap` — is hosting an OData V4 API for the Materials and Queries entities, a Fiori Elements list report and object page for browsing documents and running queries, and an attachment handling layer that stores uploaded PDFs in HANA and triggers the Python agent's ingestion pipeline when new documents arrive.

The two services communicate over HTTPS through Cloud Foundry's routing layer. Credentials — HANA connection details, GCP project identifiers, LangChain API keys — live in a User-Provided Service that binds to both containers at runtime, never appearing in source code or deployment files.

The knowledge graph is loaded with the MSDS ontology, ready to answer structured queries about chemical properties, hazard classifications, and regulatory relationships. The vector index is ready to receive documents — each PDF uploaded through the Fiori UI will be chunked, embedded, and stored in HANA, making its contents available for semantic search immediately.

This is not a prototype running on a developer laptop. It is a deployed, scalable, cloud-native system on the same platform that hosts SAP S/4HANA, SuccessFactors, and every other SAP cloud product your organization uses.

---

## 11.12 Chapter Checkpoint

Work through this list before moving to the next chapter. Each item verifies a specific part of the deployed system and points toward the section to revisit if the check fails.

- `cf app hybrid-rag-agent` shows the application in `started` state with a route assigned. (Section 11.3)
- `curl https://hybrid-rag-agent.<domain>/health` returns a JSON response with no error fields. (Section 11.8)
- The User-Provided Service `hybrid-rag-agent-env` exists and is bound to both applications. (Section 11.4)
- `cf deploy` completed without errors and both applications appear in `cf apps`. (Section 11.5)
- A BTP Destination named `hybrid-rag-agent` exists in the subaccount, pointing to the Python agent URL. (Section 11.6)
- `curl -X POST .../admin/load-ontology` returned a 200 status code. (Section 11.7)
- A direct `curl` POST to `/query` returns an answer with a retrieval path. (Section 11.8)
- The Fiori Elements UI loads at the CAP application URL without errors in the browser console. (Section 11.8)

If every item on this list is green, the system is deployed and functional. The next chapter addresses operational concerns — observability, performance tuning, and the integration patterns that allow this system to participate in broader SAP workflows.
