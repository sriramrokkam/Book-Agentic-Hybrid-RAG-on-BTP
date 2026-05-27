# Chapter 9: CAP Node.js OData V4 — The SAP-Native API Layer + Fiori Elements UI

The CAP Node.js service does three things: it provides a Fiori Elements UI that SAP users already know how to use, it enforces material-number validation against real S/4HANA product master data, and it proxies document processing and chat queries to the FastAPI agent backend. This separation is deliberate — SAP enterprise standards (OData V4, Fiori UX, BTP security) live in the CAP layer; AI orchestration and HANA data access live in the Python layer.

Chapters 7 and 8 built the intelligence engine: a Python FastAPI service that receives a question, dispatches it to parallel retrieval chains, and returns a grounded answer. That engine is a standard Python web service. It knows nothing about Fiori, OData, or SAP authentication. To bring this capability into an SAP enterprise environment — where business users work in SAP Fiori applications, where material numbers are validated against S/4HANA product master data, and where access is controlled by BTP security services — you need a second layer. That layer is CAP.

By the end of this chapter you will have a complete, deployable front-end: a Fiori Elements list report showing all uploaded material documents with their processing status, an object page with action buttons to process files and run queries, and an integrated chat interface that calls the hybrid RAG agent and returns answers with the retrieval path shown. No custom JavaScript UI code required.

---

## 9.1 Why CAP?

Before writing a single line of code, it is worth understanding why CAP is the right choice for this layer rather than a simple Express server or a Next.js front-end.

**OData V4 compatibility.** Every SAP system — S/4HANA, SuccessFactors, BTP Integration Suite — speaks OData. By exposing your agent through a CAP service you make it consumable by any SAP client, including Fiori Elements, SAP Analytics Cloud, and ABAP programs via HTTP calls. A plain REST API would require a custom client in every consumer; an OData endpoint works out of the box.

**Fiori Elements without custom code.** SAP Fiori Elements is a UI framework that generates complete, SAP-consistent user interfaces from OData metadata and annotations. You do not write HTML, CSS, or JavaScript for the list report or the object page — you write CDS annotations, and the framework generates the UI at runtime. For an internal tool, this means a production-quality interface with zero front-end development effort.

**Real S/4HANA product master integration.** The Material Number field in the Fiori UI shows a value help backed by real S/4HANA product data via the API_PRODUCT_SRV external service. When a user uploads a document, they select the material from their actual SAP product master. This closes the loop between the AI layer on BTP and the system of record in S/4HANA — and it is what makes this a genuine enterprise integration rather than a standalone demo.

**Integrated attachment handling.** The `@cap-js/attachments` plugin gives you a fully managed file upload and retrieval mechanism that stores binaries in the configured database and exposes them through the OData protocol. Without it, you would need to write your own multipart upload handler, storage integration, and metadata tracking. With it, you write two lines of CDS.

**Deployment to BTP Cloud Foundry.** A CAP service is designed to run on SAP BTP. The `@sap/cds` framework handles XSUAA authentication, SAP HANA connection management via `@cap-js/hana`, and binding to SAP BTP services through the standard VCAP_SERVICES mechanism. When you deploy to BTP, you get enterprise-grade authentication and database connection pooling with no additional configuration.

The key decision in this architecture is what CAP does *not* do: it does not run the Python agent. CAP handles the OData protocol, the attachment storage, and the Fiori UI. The Python FastAPI service handles LangGraph orchestration, SPARQL queries, and vector search. This separation keeps each service focused on what it does best.

---

## 9.2 The two-process architecture

Understanding that CAP and FastAPI are separate processes is the most important architectural concept in this chapter. Many developers assume that because a CAP service can call external APIs, the agent logic should be imported into the Node.js process. That assumption leads to a tightly coupled system that is difficult to test, impossible to scale independently, and requires Node.js developers to maintain Python code.

The correct architecture is clean separation:

```
User browser
    |
    | HTTP (Fiori Elements, OData V4)
    v
CAP Node.js  (port 4004)
    |
    | HTTP (axios, JSON / multipart)
    v
Python FastAPI  (port 8000)
    |
    |-- HANA Cloud (vector store, Knowledge Graph)
    |-- Google Vertex AI (Gemini LLM + text-embedding)
    |-- LangGraph (agent orchestration)
```

The CAP service is the API gateway and UI host. It knows how to speak OData and how to manage CDS entities. It knows nothing about SPARQL, embeddings, or LangGraph. The FastAPI service is the intelligence engine. It knows nothing about OData, Fiori, or attachment storage.

Communication between the two is intentionally simple: HTTP with JSON bodies for queries, HTTP with multipart form data for file uploads. The `BACKEND_URL` environment variable controls where CAP sends its requests. In local development this is `http://localhost:8000`. On BTP it is the URL of the deployed FastAPI CF application.

This separation has three practical benefits. First, you can develop and test each service independently — mock the CAP service when testing the Python agent, and stub the agent when testing the CAP service. Second, you can scale them independently — the agent is CPU and memory intensive during LLM calls, while CAP is lightweight. Third, you can replace either without touching the other — swap the Python agent for a different implementation and the CAP service requires no changes, as long as the HTTP contract is preserved.

---

## 9.3 The CDS data model

The data model lives in `db/schema.cds`. It defines two entities and a status type.

The namespace `msds.kg` reflects the first document type in our implementation — Material Safety Data Sheets, processed into a Knowledge Graph. In a production deployment serving multiple document categories (invoices, batch certificates, quality inspection reports, maintenance manuals, legal filings), you would use a broader namespace — `documents.kg` or `materials.intelligence` — and extend the schema with a `documentType` field. The core entity structure is identical regardless: `materialNumber` as the anchor, `attachments` as the document store, status tracking fields for both pipeline stages.

```cds
namespace msds.kg;
using { managed } from '@sap/cds/common';
using { Attachments } from '@cap-js/attachments';

type Status : String(20) enum {
    Pending    = 'Pending';
    Processing = 'Processing';
    Completed  = 'Completed';
    Error      = 'Error';
}

entity FileAttachments : Attachments {
    up_ : Association to Files;
}

entity Files : managed {
    key materialNumber      : String(40);
    status                  : Status default 'Pending';
    fileHash                : String(64) @assert.unique;
    triples                 : Integer default 0;
    vectors                 : Integer default 0;
    vectorStatus            : Status  default 'Pending';
    errorMessage            : String(500);
    processingStartedAt     : DateTime;
    retryCount              : Integer default 0;
    attachments             : Composition of many FileAttachments on attachments.up_ = $self;
}
```

The `Status` type is declared as a CDS enum. This matters because enums generate value-restricted OData properties, which Fiori Elements renders as proper dropdown fields with validation. The string values (`'Pending'`, `'Processing'`, etc.) are what get stored in the database and sent over the wire.

The `Files` entity extends `managed`, which is a built-in CDS aspect from `@sap/cds/common`. This single word gives you four fields for free: `createdAt`, `createdBy`, `modifiedAt`, and `modifiedBy`. The framework populates them automatically on every insert and update. You never need to write that logic yourself.

The dual-status design — `status` for the Knowledge Graph pipeline and `vectorStatus` for the vector pipeline — reflects a real operational requirement. The two pipelines run independently. A document can have its triples extracted successfully while the vector embedding is still running, or vice versa. Tracking them separately means your UI can show accurate, granular progress rather than a single boolean that masks which step failed.

`fileHash` carries the `@assert.unique` annotation. This is a CAP-level constraint that generates a database unique index and returns a meaningful OData error if you attempt to upload the same file twice. Without this, operators could accidentally trigger redundant processing.

The `FileAttachments` entity extends `Attachments` from `@cap-js/attachments`. This is the entire attachment implementation — one line of CDS. The plugin handles binary storage, MIME type detection, streaming upload and download, and exposes the attachment content through the standard OData `$value` endpoint. The `up_` association links each attachment back to its parent `Files` record, following the standard CAP composition pattern.

The `attachments` field on `Files` is a `Composition of many FileAttachments`. Compositions in CDS mean deep operations: when you delete a `Files` record, all its attachments are deleted automatically. When you read a `Files` record with `$expand=attachments`, you get the attachment metadata in a single request.

---

## 9.4 The service definition

The service is defined in `srv/service.cds`. This file does three things: it projects the data model entities into the service, it adds virtual fields for UI display, and it declares the actions and functions that map to agent operations.

```cds
using { msds.kg as db } from '../db/schema';

@path: '/odata/v4/documents'
service DocumentService {
    @odata.draft.enabled
    entity Documents as projection on db.Files {
        *,
        virtual kgDisplay               : String,
        virtual vecDisplay              : String,
        virtual statusCriticality       : Integer,
        virtual vectorStatusCriticality  : Integer
    }
    actions {
        action processFile() returns { status: String; message: String; attachmentCount: Integer };
        @(Common.IsActionCritical: true)
        action deleteFile() returns { status: String; message: String };
    };

    action chatQuery(message: String, materialNumber: String) returns { answer: String; path_used: many String };

    function pollStatus(materialNumber: String) returns {
        status   : String;
        triples  : Integer;
        vectors  : Integer;
        kg_done  : Boolean;
        vec_done : Boolean;
    };
}
```

The `@path` annotation sets the OData service root URL. All entity sets, actions, and functions under this service will be accessible at `/odata/v4/documents`. This path is registered by `@sap/cds` automatically when the server starts.

`@odata.draft.enabled` on the `Documents` entity activates SAP Fiori draft handling. Draft is the standard pattern for transactional data entry in Fiori applications. The framework saves partial edits server-side before the user explicitly confirms them — preventing data loss on accidental navigation and matching how SAP Fiori works for purchase orders, material master records, and every other transactional document in the SAP ecosystem. In practice, for this application it means the create-new-document flow works correctly in the Fiori UI without any additional handler code — users can enter the material number, attach the PDF, and save as draft before committing to processing.

The `virtual` fields deserve particular attention. A virtual field is projected into the OData response but has no corresponding database column. The values are computed in the service handler at read time. Here, `kgDisplay` and `vecDisplay` are formatted strings like "Completed (1,247 triples)" that combine the status and the count into a single display value. The `statusCriticality` and `vectorStatusCriticality` fields are integers (0–3) that Fiori Elements interprets as colour codes: 0 is neutral, 1 is error (red), 2 is warning (orange), 3 is positive (green). By computing criticality as a virtual field, you keep the colour logic in the service layer rather than scattering it across annotations.

The distinction between `action` and `function` in OData V4 is important. Actions have side effects — they modify state. Functions are read-only — they return computed data without modifying anything. `processFile` and `deleteFile` are bound actions: they operate on a specific `Documents` entity instance, identified by its key. `chatQuery` is an unbound action: it accepts parameters directly and operates at the service level, not on a specific entity. `pollStatus` is an unbound function: it retrieves current status from the backend without changing anything, making it safe to call repeatedly in a polling loop.

The `@(Common.IsActionCritical: true)` annotation on `deleteFile` tells Fiori Elements to show a confirmation dialog before invoking the action. The user must explicitly confirm the destructive operation. One annotation; no custom dialog code.

---

## 9.5 The Products entity and S/4HANA value help

The `DocumentService` extends beyond the `Files` entity. The service also exposes a `Products` entity sourced from the `API_PRODUCT_SRV` external service — the standard SAP OData API for product master data in S/4HANA.

This is architecturally significant. The `materialNumber` field on the `Documents` entity carries a `@Common.ValueList` annotation that points to the `Products` entity. When a business user opens the Fiori UI to upload a new document and clicks into the Material Number field, the Fiori value help fires an OData request to `DocumentService/Products`. CAP proxies that request to the configured S/4HANA system and returns the matching product master records.

What this means operationally: a quality manager uploading a batch certificate does not type a material number from memory — they search and select from their actual SAP product master. The material number that anchors the document in the Knowledge Graph and vector store is the same material number that exists in their S/4HANA system. When a question comes back through chatQuery — "What are the storage conditions for this material?" — the answer is grounded in data that is tied to the real product record.

This is what makes this a genuine enterprise integration rather than a standalone demo. The AI capability on BTP is connected to the system of record in S/4HANA through standard SAP OData APIs and standard BTP Destination Service connectivity. Changing the S/4HANA destination in the BTP Cockpit is the only configuration needed to point this system at a different S/4HANA landscape.

---

## 9.6 The callBackend helper

Every handler in `srv/service.js` that needs to communicate with the Python agent uses the same `callBackend` helper function. This centralisation matters: the URL of the backend, the authentication headers, the error handling, and the timeout configuration all live in one place.

```javascript
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

async function callBackend({ method, path, jsonBody, formData }) {
  const response = await axios.request({
    method,
    url: `${BACKEND_URL}${path}`,
    headers: formData ? formData.getHeaders() : { "Content-Type": "application/json" },
    data: formData || jsonBody,
  });
  return response.data;
}
```

The `BACKEND_URL` environment variable is read once at module load time. In local development you set this to `http://localhost:8000` in a `.env` file in the `cap-srv/` directory, and `@sap/cds` loads it automatically via `dotenv`. On BTP, you set it as an environment variable in your Cloud Foundry application manifest or as a user-provided service binding. The fallback to `http://localhost:8000` means the service starts without any configuration during development — the fallback is safe because there is no production environment where port 8000 is the correct URL.

The `formData ? formData.getHeaders()` conditional is the key to handling two different call types with one function. When `formData` is provided, the request is a multipart upload and axios must use the boundary-aware headers that `form-data` generates. When `jsonBody` is provided, the content type is `application/json`. Getting this wrong produces a `400 Bad Request` from the FastAPI endpoint.

Axios is used here rather than the native Node.js `fetch` because `form-data` integrates with axios through the `getHeaders()` and pipe mechanism. Node.js 18+ `fetch` supports `FormData`, but the `@cap-js/attachments` binary retrieval returns a Node.js `Buffer`, and converting that buffer to a browser-compatible `FormData` in Node.js requires additional tooling. Axios with the `form-data` package is the simpler path.

---

## 9.7 Action handlers

### processFile

When a user clicks Process File in the Fiori UI, they are initiating the full ingestion pipeline. The Fiori button fires an OData action request to the CAP service. CAP reads the PDF from the attachment store, constructs a multipart request, and POSTs it to the FastAPI backend at `/process-upload`. FastAPI returns 202 Accepted immediately — it has queued the job but not finished it. CAP updates the `Files` record to `Processing` and returns to the Fiori UI. The Fiori UI then begins polling `pollStatus()` on a timer. As the FastAPI pipeline runs — chunking the PDF, generating triples, embedding passages — the `triples` and `vectors` counts climb until both pipelines report completion. The Fiori UI reflects those counts as they update, giving the operator a live view of ingestion progress without any WebSocket infrastructure.

The `processFile` action is the most complex handler because it bridges two protocols: OData binary retrieval and HTTP multipart upload. The handler must read the attachment binary from the CAP attachment store, then stream it to the FastAPI `/process-upload` endpoint as a multipart request.

```javascript
srv.on("processFile", Documents, async (req) => {
  const { materialNumber } = req.params[0];

  // Retrieve attachment metadata from the CAP entity
  const attachments = await SELECT.from(db.Files, materialNumber)
    .columns("attachments");

  if (!attachments || attachments.attachments.length === 0) {
    return req.error(400, "No attachment found. Please upload a PDF first.");
  }

  const attachment = attachments.attachments[0];

  // Read the binary content through the @cap-js/attachments API
  const content = await cds.run(SELECT.one.from(db.FileAttachments)
    .where({ ID: attachment.ID }));

  const buffer = content.content; // Buffer from the attachment plugin
  const filename = attachment.filename || `${materialNumber}.pdf`;
  const contentType = attachment.mimeType || "application/pdf";

  // Build multipart form data for the FastAPI endpoint
  const FormData = require("form-data");
  const formData = new FormData();
  formData.append("file", buffer, { filename, contentType });
  formData.append("graphName", materialNumber);

  await callBackend({ method: "POST", path: "/process-upload", formData });

  // Mark the record as processing
  await UPDATE(db.Files).set({
    status: "Processing",
    vectorStatus: "Processing",
    processingStartedAt: new Date().toISOString()
  }).where({ materialNumber });

  return {
    status: "processing",
    message: "File submitted for processing.",
    attachmentCount: attachments.attachments.length
  };
});
```

The `req.params[0]` contains the entity key of the bound action target — in this case `{ materialNumber: 'ACETONE-001' }`. This is the OData V4 pattern for bound actions: the key is part of the action URL path, not the request body.

The handler updates the record status to `Processing` immediately after submitting to the backend. This is an optimistic update — it reflects what should happen, not what has completed. The actual status progression (Processing to Completed or Error) happens asynchronously as the Python agent runs. The `pollStatus` function and handler described below are how the UI tracks that progression.

### chatQuery

The `chatQuery` action is the core business value of this entire system. A quality manager, safety officer, or procurement analyst opens the document object page, types a natural language question — "What is the recommended storage temperature for this material?" or "Are there any regulatory restrictions on transport by air?" — and gets a sourced answer directly in the Fiori UI. The retrieval path shown alongside the answer tells them whether it came from the structured Knowledge Graph, the vector store, or both. No custom search interface. No manual document reading. No specialist tool to learn.

```javascript
srv.on("chatQuery", async (req) => {
  const { message, materialNumber } = req.data;

  const result = await callBackend({
    method: "POST",
    path: "/query",
    jsonBody: {
      question: message,
      material_number: materialNumber,
      chat_history: []
    }
  });

  return {
    answer: result.answer,
    path_used: result.path_used || []
  };
});
```

The `chat_history: []` field sends an empty history on every call. This makes every `chatQuery` invocation stateless from the agent's perspective. For a document Q&A system where questions are typically independent lookups, stateless queries are correct. If you were building a multi-turn conversational interface, you would maintain a conversation ID in the client and accumulate history on the server side. That is a separate concern — `chatQuery` can be extended to accept a `sessionId` parameter without changing anything in the action definition or the backend API contract.

The `path_used` return value is an array of strings that the Python agent populates with the retrieval path it took: `["kg_chain"]`, `["vector_chain"]`, or `["kg_chain", "vector_chain"]`. Surfacing this in the UI gives users transparency into the agent's reasoning — they can see whether the answer came from the Knowledge Graph, the vector store, or both.

### deleteFile

The `deleteFile` handler triggers a cascading cleanup: remove the Knowledge Graph triples from HANA, remove the vector embeddings from HANA, then delete the CAP record and its attachments.

```javascript
srv.on("deleteFile", Documents, async (req) => {
  const { materialNumber } = req.params[0];

  // Instruct the Python backend to clean up graph and vector data
  await callBackend({
    method: "DELETE",
    path: `/files/${encodeURIComponent(materialNumber)}`
  });

  // Delete the CAP record — composition cascades to FileAttachments
  await DELETE.from(db.Files).where({ materialNumber });

  return { status: "deleted", message: `${materialNumber} removed.` };
});
```

The `DELETE.from(db.Files)` call cascades automatically to the `FileAttachments` composition because CDS compositions enforce deep delete semantics. The `@cap-js/attachments` plugin hooks into the delete event and removes the binary files from storage. You do not need to explicitly delete the attachments — the composition and the plugin handle it.

### pollStatus

The `pollStatus` function is called by the Fiori UI on a timer after a `processFile` action to track progress. It calls the FastAPI `/status/{materialNumber}` endpoint and passes the response through.

```javascript
srv.on("pollStatus", async (req) => {
  const { materialNumber } = req.data;

  const result = await callBackend({
    method: "GET",
    path: `/status/${encodeURIComponent(materialNumber)}`
  });

  // Sync the live status back to the CAP entity
  if (result.kg_done || result.vec_done) {
    await UPDATE(db.Files).set({
      status: result.kg_done ? "Completed" : result.status,
      vectorStatus: result.vec_done ? "Completed" : result.vectorStatus,
      triples: result.triples || 0,
      vectors: result.vectors || 0
    }).where({ materialNumber });
  }

  return result;
});
```

The handler does two things: it returns the live status to the caller, and it writes the current counts back to the database. This write-through is important for the Fiori list report: the list refreshes from the OData entity, not from a live WebSocket feed. By syncing the counts on every poll, the list view stays accurate after polling completes.

---

## 9.8 Fiori Elements UI

Fiori Elements is a metadata-driven UI framework. Instead of writing a React or SAPUI5 application that fetches OData and renders HTML, you write CDS annotations that describe *what* your data means and *how* you want it presented. The framework reads the OData metadata document (which CDS generates from your service definition) and the annotation document, and assembles the UI at runtime.

This has a profound implication for development speed. A complete list report with search, sorting, and export requires approximately 50 lines of CDS annotations. The equivalent hand-written SAPUI5 application is around 500 lines of XML views and controllers, plus another few hundred lines of JavaScript. For internal tools and prototypes, Fiori Elements is consistently the better choice.

The trade-off is customisation ceiling. If you need a completely custom layout — a drag-and-drop canvas, a real-time chart with WebSocket data, a custom color scheme — Fiori Elements will fight you. For standard enterprise UI patterns — list reports, object pages, form inputs, action buttons — it covers everything you need.

For our document management and Q&A interface, the standard patterns are exactly right:

- A **list report** showing all documents with their status, triple count, and upload date
- An **object page** for each document showing its details, attachments, and action buttons
- A **chat section** on the object page where users can submit questions and see answers

All of this is generated from the CDS service definition and the annotations in `srv/annotations.cds`. There is no separate UI project, no `package.json` for the front-end, and no custom JavaScript.

The CAP + Fiori layer means this AI capability fits natively into any SAP Fiori launchpad. A quality manager, safety officer, or procurement analyst uses the same Fiori UX patterns they use across every other SAP application. The AI is invisible infrastructure — the user just asks a question and gets an answer.

---

## 9.9 Annotations explained

The annotations file `srv/annotations.cds` is where the UI is configured. It is separate from the service definition for a practical reason: the service definition describes what your API *does*, and the annotations describe how it *looks*. Keeping them separate means you can modify the UI without changing the API contract.

### HeaderInfo

```cds
annotate service.Documents with @(
    UI.HeaderInfo: {
        TypeName: 'Document',
        TypeNamePlural: 'Documents',
        Title: { Value: materialNumber },
        Description: { Value: status }
    }
);
```

`HeaderInfo` controls three things: the singular and plural names used in page titles and breadcrumbs, the main title shown on the object page header, and the subtitle beneath it. Setting `Title` to `materialNumber` means each document's object page is headed by its material number. Setting `Description` to `status` shows the current processing status directly in the page header, so the user knows at a glance whether the document has been processed.

### SelectionFields and LineItem

```cds
    UI.SelectionFields: [ materialNumber, status ],
    UI.LineItem: [
        { Value: materialNumber, Label: 'Material Number' },
        { Value: kgDisplay, Label: 'KG Status', Criticality: statusCriticality },
        { Value: vecDisplay, Label: 'Vec Status', Criticality: vectorStatusCriticality },
        { Value: createdAt, Label: 'Uploaded On' }
    ],
```

`SelectionFields` defines which fields appear in the filter bar above the list. Choosing `materialNumber` and `status` means users can search for a specific material or filter to show only documents in a particular state.

`LineItem` defines the columns in the list table. The `kgDisplay` and `vecDisplay` fields carry the `Criticality` annotation pointing to the integer fields computed in the service handler. Fiori Elements renders criticality as a colored status indicator: integers map to red, orange, and green automatically. The display strings computed in the handler — "Completed (1,247 triples)" — appear in the column alongside the color indicator. No custom cell renderer needed.

### Identification actions

```cds
    UI.Identification: [
        {
            $Type: 'UI.DataFieldForAction',
            Action: 'DocumentService.processFile',
            Label: 'Process File',
            Criticality: #Positive
        },
        {
            $Type: 'UI.DataFieldForAction',
            Action: 'DocumentService.deleteFile',
            Label: 'Delete File',
            Criticality: #Negative
        }
    ],
```

The `Identification` collection defines the action buttons that appear in the object page header toolbar. `UI.DataFieldForAction` binds a button to an OData action by its qualified name. The `Criticality` annotation sets the button color: `#Positive` renders as green (constructive action), `#Negative` renders as red (destructive action). Combined with the `Common.IsActionCritical` annotation on `deleteFile` in the service definition, the delete button is both red and protected by a confirmation dialog — two layers of friction for a destructive operation.

### FieldGroup

```cds
    UI.FieldGroup#GeneralInfo: {
        Data: [
            { Value: materialNumber },
            { Value: status },
            { Value: triples, Label: 'Triples Extracted' },
            { Value: vectors, Label: 'Vectors Stored' },
            { Value: vectorStatus, Label: 'Vector Status' }
        ]
    }
```

`FieldGroup` with an identifier (`#GeneralInfo`) defines a named group of fields. These groups are then referenced in a `Facets` annotation to assemble the object page layout. Each `Data` entry becomes a labeled field in the form. The `triples` and `vectors` integers show the current counts from the last successful processing run, giving operators the information they need to assess pipeline health.

---

## 9.10 Running locally

The local setup requires two terminal sessions — one for each process.

**Terminal 1: Start the Python FastAPI agent**

```bash
cd agents/
source .venv/bin/activate
uvicorn main:app --reload --port 8000
```

Confirm it is running by visiting `http://localhost:8000/docs` and checking that the `/query`, `/process-upload`, and `/status/{material_number}` endpoints are listed.

**Terminal 2: Start the CAP service**

First, create a `.env` file in `cap-srv/` if one does not exist:

```
BACKEND_URL=http://localhost:8000
```

Then start the server:

```bash
cd cap-srv/
npm install
cds serve
```

The `cds serve` command reads your service definition, sets up the SQLite database (for local development — replace with HANA on BTP), loads all handlers, and starts the Express server on port 4004. You will see output like:

```
[cds] - loaded model from 3 file(s):
  db/schema.cds
  srv/service.cds
  srv/annotations.cds

[cds] - connect to db > sqlite { database: ':memory:' }
[cds] - serving DocumentService { at: '/odata/v4/documents' }

[cds] - server listening on { url: 'http://localhost:4004' }
```

Open `http://localhost:4004` to see the CDS welcome page, which lists all registered services and their metadata endpoints. Open `http://localhost:4004/$fiori-preview` to access the Fiori Elements preview sandbox — a full Fiori application running against your local OData service with no deployment required.

For the Fiori Elements preview to show all features, ensure you access it via the full URL including the Fiori launchpad hash, which the welcome page provides as a clickable link.

---

## 9.11 Testing the full flow

With both services running, walk through the complete flow from document upload to agent query.

**Step 1: Create a new document record.** In the Fiori list report, click the New button. The draft mechanism activates. Click into the Material Number field — a value help opens, backed by the Products entity from API_PRODUCT_SRV. Search for and select your material. Save the draft. The record appears in the list with status `Pending`.

**Step 2: Upload a PDF attachment.** Navigate to the object page for your material. In the Attachments section, click Upload and select a PDF — an MSDS, SDS, or any document relevant to that material. The attachment is stored immediately via `@cap-js/attachments`.

**Step 3: Process the file.** Click the Process File button in the header toolbar. The handler reads the attachment binary, constructs a multipart form data request, and POSTs it to the Python agent at `http://localhost:8000/process-upload`. The record status changes to `Processing` immediately.

**Step 4: Watch the dual status.** Open a separate terminal and call `pollStatus` manually to watch the counts grow:

```bash
curl "http://localhost:4004/odata/v4/documents/pollStatus(materialNumber='ACETONE-001')"
```

You will see `kg_done` and `vec_done` flip to `true` as each pipeline completes, and the `triples` and `vectors` counts increment. The Fiori object page, if you have it open and refresh it, shows the same values updating.

**Step 5: Run a query.** Once both pipelines are complete, use the `chatQuery` action. In the Fiori UI this can be triggered via an action dialog bound to the `chatQuery` unbound action. From the command line:

```bash
curl -X POST http://localhost:4004/odata/v4/documents/chatQuery \
  -H "Content-Type: application/json" \
  -d '{"message": "What are the first aid measures for skin contact?", "materialNumber": "ACETONE-001"}'
```

The response includes the `answer` field with the agent's response and the `path_used` array indicating which retrieval chains contributed: `["kg_chain", "vector_chain"]` means both paths were used, which is the expected behavior for this type of factual question about a chemical document.

---

## 9.12 What you can do after this chapter

The system is now complete from ingestion to query to UI. You have:

- A Python FastAPI service that runs the hybrid RAG agent with parallel KG and vector retrieval
- A CAP OData V4 service that manages document records, attachment storage, and proxies requests to the agent
- A Fiori Elements UI generated entirely from CDS annotations
- A value help on Material Number backed by real S/4HANA product master data via API_PRODUCT_SRV

The natural next steps are:

**Add conversational history to chatQuery.** Extend the `chatQuery` action to accept an optional `sessionId` parameter. Store conversation turns in a new CDS entity `ChatSession`. On each call, retrieve the session history and pass it to the FastAPI `/query` endpoint as `chat_history`. This turns a single-shot Q&A into a stateful conversation without changing the agent logic.

**Add a polling timer to the Fiori UI.** Write a Fiori Elements custom section that calls `pollStatus` every 5 seconds while the document status is `Processing`, updating the form fields and stopping the timer when both pipelines are complete. This is one of the few cases where a small amount of custom SAPUI5 controller code in the Fiori application is justified.

**Extend to additional document types.** The schema is built for this. Add a `documentType` field to `Files`, extend the Status enum if needed, and configure the FastAPI ingestion pipeline to handle invoice layouts, batch certificate formats, or quality inspection report structures. The CAP layer, the Fiori UI, and the chatQuery interface require no changes.

**Deploy to SAP BTP Cloud Foundry.** Replace the SQLite database with HANA Cloud by setting the `cds.requires.db.kind` to `hana` and binding the `hana` service. Set `BACKEND_URL` to the deployed FastAPI service URL. Run `cf push` from `cap-srv/`. The CAP service connects to HANA automatically via the `VCAP_SERVICES` binding. Chapter 10 covers this in full.

**Add XSUAA authentication.** Bind an XSUAA service instance to the CAP application. Add `@requires: 'authenticated-user'` to the `DocumentService` definition. The CAP framework validates JWT tokens from XSUAA on every request with no additional handler code.

---

## 9.13 Checkpoint checklist

Before moving to the next chapter, verify the following:

- `cds serve` starts without errors and outputs the service URL at port 4004
- The Fiori Elements preview is accessible at `http://localhost:4004/$fiori-preview`
- A new document can be created and saved via the Fiori list report
- The Material Number value help returns results from the Products entity
- A PDF attachment can be uploaded and is stored by `@cap-js/attachments`
- Clicking Process File sends a multipart POST to the FastAPI service and returns `status: "processing"`
- The `pollStatus` function returns accurate `triples` and `vectors` counts after processing completes
- The `chatQuery` action returns an `answer` string and a `path_used` array
- The `deleteFile` action triggers the confirmation dialog (from `Common.IsActionCritical`) before executing
- The `kgDisplay` and `vecDisplay` columns in the list report show colored status indicators (green for Completed, red for Error)

If all ten items pass, your SAP-native API layer and Fiori Elements UI are working correctly. The full system — Python agent, CAP service, and Fiori UI — is operational end to end.

---

## Summary

This chapter added the enterprise presentation layer to the hybrid RAG system. We built a CAP Node.js OData V4 service that manages document records and attachments through CDS entities, and exposes file processing and query operations through bound and unbound OData actions. The `materialNumber` field carries a value help backed by real S/4HANA product master data through API_PRODUCT_SRV — the connection between the AI capability on BTP and the system of record in S/4HANA. We built a `callBackend` helper that proxies all agent operations to the Python FastAPI service via HTTP, keeping the two processes completely decoupled. We generated a complete Fiori Elements UI — list report with colored status columns, object page with action buttons, and attachment handling — from CDS annotations alone, with no custom JavaScript or HTML.

The architectural principle throughout is separation of concerns: CAP owns the OData protocol, the S/4HANA integration, and the UI; FastAPI owns the intelligence. Neither service knows the internals of the other. They communicate through a narrow, stable HTTP contract. This separation makes both services easier to test, easier to scale, and easier to evolve independently.

The CAP + Fiori layer means this AI capability fits natively into any SAP Fiori launchpad. The user just asks a question and gets an answer.
