# Appendix D: Joule A2A Integration

---

> **Joule 2.0 notice.** At the time this book was written, SAP announced **Joule 2.0** with native Agent-to-Agent (A2A) protocol support as a first-class feature. The implementation in this appendix covers **Joule 1.x A2A** — the pattern that is available today on SAP S/4HANA Cloud Public Edition. The YAML structure, capability packaging, and deployment flow may change with Joule 2.0. The core concept — wrapping an external agent behind a Joule capability with a declarative YAML interface — will remain the same. We will update this appendix when Joule 2.0 is generally available.

---

> **Enterprise prerequisite.** This appendix requires **SAP S/4HANA Cloud Public Edition** or **SAP SuccessFactors** with Joule enabled. It is NOT available on BTP free trial. If you do not have this subscription, read this appendix to understand the pattern and return to it when you have access.

---

Throughout this book we have built the intelligence layer: a Python FastAPI service that orchestrates a LangGraph hybrid RAG agent, stores knowledge in SAP HANA Cloud, and returns accurate answers about Material Safety Data Sheets. In Chapter 9 we gave that agent a Fiori Elements front-end. This appendix adds a third access channel: SAP Joule, the AI assistant embedded directly in S/4HANA and SuccessFactors.

The value is significant. A procurement specialist in S/4HANA who is looking at a purchase order for Acetone can ask Joule "what are the PPE requirements for this material?" without leaving their context. Joule routes that question to our hybrid RAG agent, which queries the Knowledge Graph and vector store, and returns the answer inside the Joule chat panel. The user never opens a separate application.

That routing is handled by the A2A protocol. This appendix explains how it works, walks through every YAML file in the `joule/` directory of the project, and shows you how to package and deploy the capability.

---

## D.1 What Is Joule A2A?

Joule is SAP's conversational AI assistant. It is embedded in S/4HANA Cloud, SuccessFactors, and other SAP products. When a user types a question, Joule matches it to a registered scenario, executes a function, and presents the result.

In early versions of Joule, functions were limited to SAP's own built-in skills. The A2A (Agent-to-Agent) extension allows Joule to call an external HTTP endpoint and treat the response as a Joule answer. The external endpoint — in our case, the Python FastAPI service — is the "agent." Joule is the "Joule agent" calling it.

The A2A protocol used in Joule 1.x is a lightweight request-response protocol over HTTP. Joule sends a POST request to your agent endpoint with a message payload, and your agent returns a structured response. The YAML files in the `joule/` directory describe the capability: what scenarios trigger it, what parameters to pass, and how to map the result back to Joule's response format.

This is deliberately simple. There is no persistent connection, no streaming, and no callback mechanism. Joule sends a request and waits up to 15 seconds for a response. That constraint shapes everything about the endpoint design, as we will discuss in section D.6.

---

## D.2 How the Pieces Fit Together

Before diving into individual files, it helps to see the full call chain.

```
User types question in Joule chat panel (S/4HANA or SuccessFactors)
    |
    | Joule matches question to a registered scenario
    v
msds_query.yaml  (scenario — intent matching)
    |
    | Scenario routes to function
    v
msds_chat.yaml   (function — builds the HTTP request)
    |
    | system_alias resolves MSDS_KG_Agent -> BTP Destination
    v
BTP Destination: MSDS-KG-RAG-Agent
    |
    | HTTP POST /a2a
    v
Python FastAPI  (agents/main.py — the /a2a endpoint)
    |
    |-- Knowledge Graph chain  (SPARQL -> HANA RDF store)
    |-- Vector chain           (embedding -> HANA vector store)
    |-- LLM synthesis          (Vertex AI Gemini)
    v
JSON response  {"type": "finalAnswer", "message": "..."}
    |
    | Function maps chat_result.body.message to answer
    v
Joule presents answer in chat panel
```

The BTP Destination is the key indirection point. It decouples the YAML files from the actual URL of your FastAPI service. When you redeploy the agent to a new URL, you update the destination once in BTP Cockpit; the YAML files are unchanged.

---

## D.3 The File Structure

The complete `joule/` directory in this project contains the following files:

```
joule/
├── da.sapdas.yaml
└── msds_capability/
    ├── capability.sapdas.yaml
    ├── capability_context.yaml
    ├── functions/
    │   ├── msds_chat.yaml
    │   └── msds_status.yaml
    └── scenarios/
        ├── msds_query.yaml
        └── msds_status.yaml
```

There are five distinct file types, each with a specific responsibility. We examine them in the order Joule processes them.

---

## D.4 The Five Files Explained

### D.4.1 da.sapdas.yaml — The Root Agent Declaration

```yaml
schema_version: 1.0.0
name: msds_kg_agent
capabilities:
  - type: local
    folder: ./msds_capability
```

This is the entry point. It tells the Joule deployment tooling (`sapdas` CLI or Joule Admin UI) that there is an agent named `msds_kg_agent` and that its capability lives in the `./msds_capability` folder.

The `type: local` means the capability folder is included inside the same `.daar` package. An alternative is `type: remote`, which references a capability published to a shared registry — a pattern used when multiple agents share a common capability. For our purposes, local is simpler and self-contained.

The `schema_version: 1.0.0` refers to the outer agent declaration format. The capability itself uses a different, higher schema version, which is declared inside `capability.sapdas.yaml`.

### D.4.2 capability.sapdas.yaml — The Capability Metadata

```yaml
schema_version: 3.28.0
metadata:
  display_name: MSDS Safety Knowledge Agent
  namespace: com.sap.msds
  name: msds_kg_agent
  version: 2.0.0-SNAPSHOT
  description: >-
    Answer questions about Material Safety Data Sheets (MSDS): hazards,
    PPE requirements, first aid, storage conditions, and regulatory compliance.
    Uses hybrid RAG (Knowledge Graph + Vector search) for accurate answers.
system_aliases:
  MSDS_KG_Agent:
    destination: MSDS-KG-RAG-Agent
```

This file describes the capability to Joule's capability registry. Several fields deserve explanation.

The `schema_version: 3.28.0` is the capability schema version, not the agent declaration version. The two schemas are independent. Use the version that matches your Joule environment; as of this writing, 3.28.0 is current for S/4HANA Cloud Public Edition 2024.

The `namespace: com.sap.msds` provides a unique prefix to avoid name collisions with other capabilities in the same Joule instance. Use a reverse-DNS style string based on your organization's domain, not `com.sap` for your own capabilities in production; the `com.sap` namespace is used here because this is a reference implementation.

The `version: 2.0.0-SNAPSHOT` uses the Maven convention for pre-release versions. The `-SNAPSHOT` suffix signals that this version is not yet stable. The `.daar` package filename derives from these fields, as we will see in section D.8.

The `system_aliases` section is where the BTP Destination mapping lives. The alias `MSDS_KG_Agent` is the logical name used inside function YAML files. The `destination: MSDS-KG-RAG-Agent` is the name of the BTP Destination that Joule will look up at runtime to resolve the actual URL. This indirection is the reason the YAML files contain no hard-coded URLs.

### D.4.3 capability_context.yaml — Persisted Variables

```yaml
variables:
  - name: thread_id
  - name: material_number
  - name: task_id
```

Joule maintains a capability context per conversation. Variables declared here persist across multiple turns of the same conversation. When a user asks "what are the hazards?" and then follows up with "what about the storage conditions?", Joule can carry the `material_number` forward without the user repeating it.

The scenario YAML files (section D.4.5) write to these variables at the end of each function call. Functions read from them via `$capability_context.material_number`. This is how the agent maintains conversational state without any server-side session — the state rides in the Joule context.

### D.4.4 Function YAML Files — The HTTP Request Builders

Function files define how Joule constructs and sends an HTTP request to the agent. The project has two functions.

**msds_chat.yaml** handles conversational queries:

```yaml
parameters:
  - name: user_message
    optional: true
  - name: material_number
    optional: true
action_groups:
  - actions:
      - type: status-update
        message: Searching MSDS knowledge base...
      - type: set-variables
        variables:
          - name: msg
            value: "<? user_message != null ? user_message : $transient.input.text.raw ?>"
      - type: set-variables
        variables:
          - name: tid
            value: "default"
      - type: set-variables
        variables:
          - name: mat
            value: "<? material_number != null ? material_number : '' ?>"
      - type: api-request
        method: POST
        system_alias: MSDS_KG_Agent
        path: /a2a
        headers:
          Content-Type: application/json
        body: >
          {"Message": "<? msg ?>", "contextId": "<? tid ?>", "taskId": "<? mat ?>"}
        timeout: 15
        result_variable: chat_result
result:
  answer: "<? chat_result.body.message ?>"
  thread_id: "<? tid ?>"
  material_number: "<? chat_result.body.taskId != null ? chat_result.body.taskId : mat ?>"
```

**msds_status.yaml** handles document processing status checks:

```yaml
parameters:
  - name: material_number
    optional: true
action_groups:
  - actions:
      - type: status-update
        message: Checking processing status...
      - type: set-variables
        variables:
          - name: mat
            value: "<? material_number != null ? material_number : '' ?>"
      - type: api-request
        method: POST
        system_alias: MSDS_KG_Agent
        path: /a2a
        headers:
          Content-Type: application/json
        body: >
          {"Message": "status", "contextId": "status-check", "taskId": "<? mat ?>"}
        timeout: 15
        result_variable: chat_result
result:
  status_message: "<? chat_result.body.message ?>"
  material_number: "<? mat ?>"
```

The function file is the most complex part of the A2A configuration. The `action_groups` field contains a sequential list of actions that Joule executes before making the HTTP request.

The `status-update` action shows a loading message in the Joule chat panel while the request is in flight. This is important for user experience: a 10-second wait without feedback feels like a hang. Showing "Searching MSDS knowledge base..." communicates that work is in progress.

The `set-variables` actions build local variables that are used in the request body. Notice the ternary expression in the `msg` variable assignment — this is the SpEL-like expression language discussed in section D.5.

The `api-request` action sends the HTTP request. The `system_alias: MSDS_KG_Agent` references the alias defined in `capability.sapdas.yaml`, which resolves to the BTP Destination. The `timeout: 15` is Joule's maximum wait time in seconds; any response that takes longer will be discarded. The `result_variable: chat_result` names the variable that receives the parsed response body.

The `result` section at the bottom maps response fields to named outputs. These output names are what scenario files reference via `$target_result.*`.

### D.4.5 Scenario YAML Files — Intent Matching and Routing

Scenario files are what Joule uses to decide which function to call. They contain plain-language descriptions that Joule's NLU engine matches against the user's input.

**msds_query.yaml:**

```yaml
description: >-
  Answer questions about Material Safety Data Sheets (MSDS) for chemicals and materials.
  This covers hazard information, GHS classification, PPE requirements, protective equipment,
  first aid procedures, storage conditions, incompatible materials, regulatory compliance,
  REACH, flammability, toxicity, exposure limits, and safety handling instructions.
  Examples: hazards of Acetone, PPE for Methanol, how to store WD-40, material 200001001 safety data.
target:
  type: function
  name: msds_chat
  parameters:
    - name: material_number
      value: $capability_context.material_number
response_context:
  - value: $target_result.answer
    description: MSDS safety answer from knowledge base
capability_context:
  - name: thread_id
    value: $target_result.thread_id
  - name: material_number
    value: $target_result.material_number
```

**msds_status.yaml:**

```yaml
description: >-
  Check the processing status of an MSDS material document including ingestion progress,
  number of Knowledge Graph triples extracted, number of vectors stored,
  and whether document processing is complete or still in progress.
target:
  type: function
  name: msds_status
  parameters:
    - name: material_number
      value: $capability_context.material_number
response_context:
  - value: $target_result.status_message
    description: Processing status for the material
capability_context:
  - name: material_number
    value: $target_result.material_number
```

The `description` field is the most important part of a scenario file. Write it as a dense enumeration of the topics the scenario covers, not as a sentence. Joule's NLU engine scores the user's input against this description using semantic similarity; the richer and more specific the description, the more accurately Joule routes questions to the right scenario. The examples at the end ("hazards of Acetone, PPE for Methanol") act as few-shot hints.

The `target` section names the function to call and passes parameters from the capability context. Because `material_number` is stored in `$capability_context.material_number` from a previous turn, Joule can carry it forward without the user repeating it.

The `response_context` section tells Joule what text to present in the chat panel. The `$target_result.answer` is the output field named in the function's `result` section.

The `capability_context` section writes values back to the persistent context after the function completes. This is the write path; the `$capability_context.*` reference in the function's parameters is the read path.

---

## D.5 The SpEL-like Expression Language

Joule's YAML files use a small expression language enclosed in `<? ?>` delimiters. It is similar to Spring Expression Language (SpEL) but is not identical. Understanding the four reference patterns you will encounter is sufficient for most capability development.

**`<? variable ?>`** — evaluates a local variable set by a `set-variables` action. Used inside request body strings and result mappings.

**`$transient.input.text.raw`** — the raw text the user typed in the Joule chat panel, before any NLU processing. This is the fallback message when no explicit `user_message` parameter is passed by the scenario. The ternary expression `<? user_message != null ? user_message : $transient.input.text.raw ?>` covers both cases: an explicit parameter from the scenario or the raw user input.

**`$capability_context.material_number`** — reads a named variable from the persistent capability context. This is how multi-turn conversations carry state across requests without a server-side session.

**`$target_result.answer`** — reads a named field from the function's `result` section. Used in scenario files to extract the value that Joule should present to the user, and to extract values that should be written back to capability context.

**Null-safe expressions.** Joule's expression language does not throw on null; a null reference evaluates to an empty string in string contexts and to `null` in conditional expressions. The pattern `<? chat_result.body.taskId != null ? chat_result.body.taskId : mat ?>` handles the case where the agent response does not include a `taskId` field.

**Accessing nested response fields.** `chat_result.body.message` navigates the HTTP response: `chat_result` is the variable named in `result_variable`, `.body` is the parsed JSON response body, and `.message` is a field in that body. If the response body were `{"message": "...", "status": "ok"}`, then `chat_result.body.status` would access the status field.

---

## D.6 The /a2a Endpoint

The Python FastAPI service exposes a `POST /a2a` endpoint that Joule calls. This endpoint is not in the main `agents/main.py` file in the repository skeleton — you will add it as part of this appendix. Here is what it must do and why.

### D.6.1 Dual Format Support

The A2A protocol in Joule 1.x uses a flat JSON format:

```json
{
  "Message": "What are the hazards of Acetone?",
  "contextId": "default",
  "taskId": "200001001"
}
```

The emerging standard A2A protocol (as defined by the open A2A specification that other AI frameworks are adopting) uses a JSON-RPC envelope:

```json
{
  "jsonrpc": "2.0",
  "method": "message/send",
  "params": {
    "message": {
      "parts": [{"text": "What are the hazards of Acetone?"}]
    },
    "contextId": "default",
    "taskId": "200001001"
  }
}
```

Supporting both formats in the `/a2a` endpoint means the same service can be called by Joule 1.x today and by Joule 2.0 or other A2A-compatible clients in the future. The detection logic is straightforward: if the request body contains a `jsonrpc` field, extract the message from `params.message.parts[0].text`; otherwise read from `Message` directly.

The response uses the flat format in both cases, since Joule 1.x is the primary consumer:

```json
{
  "type": "finalAnswer",
  "message": "Acetone (UN1090) is a highly flammable liquid...",
  "contextId": "default",
  "taskId": "200001001"
}
```

### D.6.2 The 15-Second Timeout Constraint

Joule imposes a hard 15-second timeout on A2A requests, as declared in the function YAML (`timeout: 15`). Any response that arrives after 15 seconds is silently discarded. The user sees nothing, which is a poor experience.

The hybrid RAG agent in Chapter 7 runs the Knowledge Graph chain and the vector chain in parallel using `asyncio.gather`. On a cold start — first request after the service has been idle — this typically takes 4 to 6 seconds including the Gemini LLM call. On a warm service it runs in 2 to 4 seconds. This is comfortably within 15 seconds under normal conditions.

The cases that can exceed 15 seconds are:

- A cold-start combined with a complex SPARQL query that traverses many graph hops
- A vector search over an unusually large embedding corpus
- A Vertex AI API call that encounters rate limiting or a degraded region

Defensive patterns to stay within the timeout:

- Set an explicit timeout on the LLM call (`request_options={"timeout": 10}` for Vertex AI clients) so the agent fails fast rather than waiting indefinitely
- Limit SPARQL query depth to two hops maximum in the Knowledge Graph chain
- Cap the number of vector chunks returned to 5 before sending to the LLM

The `/a2a` endpoint should also wrap its internal call in a Python `asyncio.wait_for` with a 12-second limit, which gives Joule a 3-second margin to receive and process the response before its own timeout fires.

### D.6.3 The Status Path

When the `Message` field is the literal string `"status"`, the endpoint checks the ingestion status of the material identified by `taskId`. It queries HANA for the triple count in the Knowledge Graph and the vector count in the vector store, and returns a natural-language summary:

```
Material 200001001: processing complete.
Knowledge graph: 847 triples. Vector store: 23 chunks.
```

This is the path used by the `msds_status.yaml` function. Because it queries HANA rather than calling the LLM, it reliably completes in under 2 seconds.

---

## D.7 The BTP Destination

The `system_aliases` section of `capability.sapdas.yaml` maps the logical name `MSDS_KG_Agent` to a BTP Destination named `MSDS-KG-RAG-Agent`. That destination must exist in the same BTP subaccount where Joule is configured.

To create the destination in BTP Cockpit:

1. Navigate to your BTP subaccount and open **Connectivity > Destinations**.
2. Click **New Destination**.
3. Fill in the fields:

| Field | Value |
|-------|-------|
| Name | `MSDS-KG-RAG-Agent` |
| Type | `HTTP` |
| URL | The URL of your deployed FastAPI service (e.g., `https://msds-rag-agent.cfapps.eu10.hana.ondemand.com`) |
| Proxy Type | `Internet` |
| Authentication | `NoAuthentication` (or `OAuth2ClientCredentials` if your service requires a token) |

4. Add the additional property:

| Property | Value |
|----------|-------|
| `HTML5.DynamicDestination` | `true` |

5. Save and test the connection using the **Check Connection** button.

The destination name in BTP Cockpit must match the `destination` field in `capability.sapdas.yaml` exactly, including case. `MSDS-KG-RAG-Agent` and `msds-kg-rag-agent` are different destinations.

For production, use OAuth2ClientCredentials authentication. Configure an XSUAA service instance on BTP, bind the FastAPI service to it, and set the destination's authentication type to `OAuth2ClientCredentials` with the client ID and secret from the service key. This ensures that only Joule — via the destination — can call the `/a2a` endpoint.

---

## D.8 Building the .daar Package

The `.daar` file is simply a ZIP archive of the capability folder, with a naming convention that encodes the namespace, capability name, and version. For this project:

```
com.sap.msds_msds_kg_agent_2.0.0-SNAPSHOT.daar
```

The name is constructed as: `{namespace}_{name}_{version}.daar`, with all dots in the namespace replaced by dots (kept as-is) and spaces replaced with underscores.

To create the package from the `joule/` directory:

```bash
cd joule/
zip -r com.sap.msds_msds_kg_agent_2.0.0-SNAPSHOT.daar msds_capability/
```

The `da.sapdas.yaml` file at the root of the `joule/` directory is not included in the `.daar` package — it is used only by the `sapdas` CLI tool for local testing. The `.daar` package contains only the `msds_capability/` folder.

Verify the package structure after creating it:

```bash
unzip -l com.sap.msds_msds_kg_agent_2.0.0-SNAPSHOT.daar
```

You should see:

```
Archive:  com.sap.msds_msds_kg_agent_2.0.0-SNAPSHOT.daar
  Length      Date    Time    Name
---------  ---------- -----   ----
      ...  2024-01-01 00:00   msds_capability/capability.sapdas.yaml
      ...  2024-01-01 00:00   msds_capability/capability_context.yaml
      ...  2024-01-01 00:00   msds_capability/functions/msds_chat.yaml
      ...  2024-01-01 00:00   msds_capability/functions/msds_status.yaml
      ...  2024-01-01 00:00   msds_capability/scenarios/msds_query.yaml
      ...  2024-01-01 00:00   msds_capability/scenarios/msds_status.yaml
```

If `da.sapdas.yaml` appears in the listing, the archive was created from the wrong directory. Delete it and repeat from inside `joule/`.

---

## D.9 Deploying to Joule

Deployment requires administrator access to the Joule configuration in your SAP S/4HANA Cloud or SuccessFactors tenant.

**Via the Joule Admin UI:**

1. Open the SAP AI Launchpad or the S/4HANA Cloud administration tile for Joule.
2. Navigate to **Agent Configuration** or **Capability Management** (the exact label varies by release).
3. Click **Upload Capability** or **Import .daar**.
4. Select the `com.sap.msds_msds_kg_agent_2.0.0-SNAPSHOT.daar` file.
5. Joule validates the package structure and the schema version. If validation passes, the capability appears in the capability list with status **Inactive**.
6. Click **Activate**. The capability is now live for users in the configured scope (all users, or a specific group depending on your Joule configuration).

**Via the sapdas CLI (if available in your environment):**

```bash
sapdas deploy --file com.sap.msds_msds_kg_agent_2.0.0-SNAPSHOT.daar \
              --tenant <your-tenant-id>
```

The CLI requires the `sapdas` tooling, which is distributed as part of the Joule Developer Experience package — available through SAP One Support Launchpad for tenants with the appropriate entitlement.

**After deployment**, verify the BTP Destination is reachable from Joule's runtime environment. The **Check Connection** result in BTP Cockpit confirms reachability from BTP, but Joule's runtime may sit in a different network segment. If Joule returns an error after deployment, use the Joule capability debug logs (in AI Launchpad under the capability details) to see the raw HTTP error from the destination call.

---

## D.10 Testing in Joule

Open the Joule chat panel in your S/4HANA Cloud or SuccessFactors session. The following conversation illustrates the expected behavior.

**Cold start — establishing material context:**

```
User:    What are the hazards of Acetone?

Joule:   [Searching MSDS knowledge base...]

         Acetone (UN1090, CAS 67-64-1) is classified as a highly flammable
         liquid and vapour (GHS02) and causes serious eye irritation (GHS07).
         The flash point is -20 degrees Celsius. The substance is not
         classified as carcinogenic or reproductively toxic under REACH.

         Source: hybrid RAG — Knowledge Graph (GHS classification, UN number)
         + vector search (handling instructions).
```

Joule matched the question to the `msds_query` scenario because the description includes "hazard information" and "GHS classification." The `material_number` capability context was empty on this first turn, so the agent resolved the material by name from the Knowledge Graph.

**Follow-up — context preserved:**

```
User:    What PPE do I need?

Joule:   [Searching MSDS knowledge base...]

         For Acetone, the required PPE is: safety glasses or goggles to
         protect against eye irritation, nitrile gloves (minimum 0.4 mm
         thickness), and adequate ventilation. A respirator is required
         if ventilation is insufficient to maintain exposure below the
         TWA of 500 ppm.
```

The user did not mention Acetone in the second question. Joule passed the `material_number` from `$capability_context.material_number` to the function, which sent it as `taskId` in the `/a2a` request. The agent used it to scope the Knowledge Graph SPARQL query to Acetone's document.

**Checking processing status:**

```
User:    What is the processing status for material 200001001?

Joule:   [Checking processing status...]

         Material 200001001: processing complete.
         Knowledge graph: 847 triples. Vector store: 23 chunks.
         Last processed: 2024-03-15 14:22 UTC.
```

Joule matched this to the `msds_status` scenario. The `material_number` was extracted from the user's message by Joule's NLU and passed as a parameter to the `msds_status` function.

---

## D.11 What Will Change with Joule 2.0

SAP's Joule 2.0 announcement describes several improvements to A2A support. Based on the public announcements available at the time of writing, the following changes are expected.

**What will likely change:**

- The YAML schema version will increment. The `schema_version: 3.28.0` in `capability.sapdas.yaml` will need to be updated to the Joule 2.0 schema version. The structure of the file is expected to remain largely compatible, with new optional fields for richer task management.
- A2A protocol alignment. Joule 2.0 is expected to align more closely with the open A2A specification, which means the JSON-RPC envelope format (`{"jsonrpc": "2.0", "method": "message/send", ...}`) will become the primary format rather than the flat format. The dual-format support in the `/a2a` endpoint described in section D.6.1 is designed for this transition.
- Richer multi-turn support. Joule 2.0 is expected to provide explicit task state management — a persistent task object with status, history, and artifacts — rather than the lightweight capability context variables used in Joule 1.x. The `thread_id` and `task_id` variables in `capability_context.yaml` will map to fields in the task object.
- Streaming support. Joule 2.0 is expected to support streaming responses for longer-running operations, which would relax the 15-second constraint.

**What will stay the same:**

- The core concept: wrapping an external HTTP agent behind a declarative YAML interface. The BTP Destination remains the routing mechanism.
- The scenario-based intent matching. Joule will continue to use semantic similarity against scenario descriptions to route questions.
- The capability packaging and deployment model. The `.daar` format or an equivalent ZIP-based package format will remain the delivery mechanism.
- The system_aliases pattern for destination indirection. Hard-coding URLs in YAML files was never the right approach; this pattern will carry forward.

When Joule 2.0 reaches general availability, the changes to this appendix will be limited to the schema version number, a revised `capability.sapdas.yaml` for the new schema, and updates to the `/a2a` endpoint to prefer the JSON-RPC format. The five-file structure and the overall architecture will remain the same.

---

## D.12 Files in the Repository

The `joule/` directory in the project repository contains the following files. Readers without an enterprise SAP subscription can study these files to understand the pattern and adapt them when access becomes available.

```
joule/
├── README.md
├── da.sapdas.yaml
└── msds_capability/
    ├── capability.sapdas.yaml
    ├── capability_context.yaml
    ├── functions/
    │   ├── msds_chat.yaml
    │   └── msds_status.yaml
    └── scenarios/
        ├── msds_query.yaml
        └── msds_status.yaml
```

The `.daar` package file (`com.sap.msds_msds_kg_agent_2.0.0-SNAPSHOT.daar`) is not committed to the repository because it is a build artifact. Generate it from the source files using the `zip` command in section D.8 whenever you need to deploy.

The `/a2a` endpoint implementation belongs in `agents/main.py` alongside the other FastAPI endpoints. It follows the same pattern as the `/query` endpoint from Chapter 7, with the dual-format request parsing and the flat-format response described in section D.6.

---

## D.13 Summary

Joule A2A bridges the gap between a custom Python agent and SAP's enterprise AI assistant. The pattern is straightforward once you understand the five-file structure: a root declaration, capability metadata with a BTP Destination alias, a context variable store, function files that build HTTP requests, and scenario files that match user intent to functions.

The constraints are real — 15 seconds is a short window for a multi-hop RAG pipeline — but manageable with parallel execution and conservative query limits. The SpEL-like expression language is minimal; the four reference patterns in section D.5 cover nearly every use case you will encounter.

The most important design decision is the BTP Destination. It keeps URLs out of YAML, which means you can redeploy the Python agent to a new host, update one field in BTP Cockpit, and every Joule capability that uses the destination automatically routes to the new endpoint. In a system where the AI layer evolves faster than the configuration layer, that decoupling is worth the extra setup step.

When Joule 2.0 arrives with native A2A support, the knowledge in this appendix transfers directly. The schema version will change; the architecture will not.
