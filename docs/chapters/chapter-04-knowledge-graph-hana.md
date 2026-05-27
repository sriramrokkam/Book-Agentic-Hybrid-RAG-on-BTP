# Chapter 4: Knowledge Graphs on SAP HANA Cloud

Vector search excels at finding relevant passages. It fails at extracting precise facts. When a procurement manager asks "Which supplier certified batch BATCH-2024-0871?", they need a name — "ACME Steel AG" — not a paragraph that mentions suppliers. When a quality engineer asks "Did this batch pass the tensile strength test?", they need "PASS" and the measured value, not a fuzzy match against test methodology paragraphs.

RDF Knowledge Graphs store facts as precise triples that can be queried exactly. This is what HANA Cloud's SPARQL engine provides. Unlike the vector store, which searches by proximity in embedding space, the Knowledge Graph traverses explicit relationships. The query is not "find what is most similar to this question" — it is "traverse this graph and return the value at this exact node."

The right answer to "What is the certificate number for batch BATCH-2024-0871?" is "QC-CERT-44781" — not a paragraph, not a summary, the exact identifier. The right answer to "Which lab certified this batch?" is "Bureau Veritas Testing GmbH" — a name, not a chunk of text.

By the end of this chapter, a SPARQL query for a batch certificate number will return exactly `["QC-CERT-44781"]` — not a paragraph that mentions it, the identifier itself.

If you have never written a line of RDF or SPARQL, do not worry. There are entire books about each. We need only enough of each to build a working hybrid RAG system. Concretely, you will need to understand three SPARQL patterns and one stored procedure call. That is the whole surface area for the rest of this book.

---

## 4.1 What is a Knowledge Graph?

A **Knowledge Graph** is a collection of facts, where each fact is expressed as a relationship between two things. That is the entire idea. The vocabulary that the RDF community uses around it can sound ceremonial — "subject-predicate-object triples organized as a directed labeled multigraph" — but strip the ceremony away and you are left with three-word sentences.

Consider the fact:

> Batch BATCH-2024-0871 was certified by supplier ACME Steel AG.

Three pieces:

| Part | Value |
|------|-------|
| Subject | BATCH-2024-0871 |
| Predicate | certified by |
| Object | ACME Steel AG |

This three-part fact is called a **triple**. A Knowledge Graph is a pile of triples. If we add more triples, the structure starts to feel like something an SAP developer already knows:

```
BATCH-2024-0871   certifiedBy        ACME Steel AG
BATCH-2024-0871   certificateNumber  QC-CERT-44781
BATCH-2024-0871   testResult         PASS (tensile)
BATCH-2024-0871   testValue          487 MPa
BATCH-2024-0871   certifyingLab      Bureau Veritas Testing GmbH
BATCH-2024-0871   certificationDate  2024-03-15
QC-CERT-44781     description        "Certificate for batch BATCH-2024-0871, steel grade S355"
```

Read those rows. You have just read a Knowledge Graph. Each row is a fact about this batch. The same subject (BATCH-2024-0871) can appear in many rows, just like a batch number can appear many times in QM-related tables. The same predicate (certifiedBy) can be reused for any other batch.

> **Note:** If you are mentally translating this to a relational table with three columns — `subject`, `predicate`, `object` — you are not wrong. That is exactly how RDF can be persisted internally. The difference from a normal table is *what kinds of questions you can ask of it*, which we will get to with SPARQL.

### Why call it a graph?

Because if you draw it, it looks like one. Subjects and objects are nodes; predicates are edges. The same certifying lab "Bureau Veritas Testing GmbH" might be the object of many batches' `certifiedBy` edges. The same certificate number might appear in many audit queries. The graph emerges naturally from shared values.

![Knowledge Graph Node: Batch Quality Certificate](docs/screenshots/diagrams/01-kg-acetone-node.png)
*Figure: RDF Knowledge Graph representation of a Batch Quality Certificate — four triples extracted from a single document, stored as a named graph in SAP HANA Cloud*

### What does this give us that a relational schema does not?

Three things, in order of how much you will care:

1. **No schema changes when facts evolve.** Tomorrow we decide batch certificates should also track `hasReTestDate`. We do not run a `DDL` migration; we just start storing triples with that predicate. The graph is permissive about what relationships exist.
2. **Queries that follow paths.** "Find me every material whose supplier is in Missouri" — that is a graph traversal. SPARQL expresses it directly. In SQL it would be a chain of joins.
3. **Identity by IRI.** Every node has a globally unique IRI (a URL-shaped identifier). This means a triple in our system can refer to the same material node that any other system uses, simply by sharing an IRI.

For our material document use case we will use the graph mainly for the first reason — flexibility — and for the *precision* it gives us at query time. A SPARQL query for a certificate number returns the certificate number, not paragraphs.

![Knowledge Graph Pipeline](docs/screenshots/diagrams/05-kg-pipeline.png)

*Figure 4.2 — Two variants of the Knowledge Graph ingestion pipeline. **With Ontology (top):** document chunks pass through entity and relationship extraction constrained by the OWL ontology, producing normalised RDF triples that are uploaded to HANA as a named graph. The ontology acts as a schema — it defines which entity types and predicates are valid, so Gemini's output is predictable and consistent. **Without Ontology (bottom):** the same pipeline runs without the constraint file. Gemini extracts whatever relationships it finds in the text. This is faster to set up but produces less consistent predicate names across documents. Our implementation uses the ontology variant — see `MSDS_Ontology.ttl` in the repository root.*

---

## 4.2 RDF and SPARQL — the standards explained plainly

**RDF** stands for Resource Description Framework. It is the W3C standard for expressing triples. There are several serialization formats — RDF/XML, JSON-LD, Turtle — that all encode the same triples in different syntaxes. We will use **Turtle** (file extension `.ttl`) because it is the most readable.

A Turtle file looks like this:

```turtle
@prefix msds: <http://msds.knowledge-graph.org/ontology#> .

msds:BATCH-2024-0871 msds:certifiedBy msds:AcmeSteelAG .
msds:BATCH-2024-0871 msds:certificateNumber "QC-CERT-44781" .
```

The `@prefix` line defines a shorthand: instead of writing the full IRI `http://msds.knowledge-graph.org/ontology#BATCH-2024-0871`, we write `msds:BATCH-2024-0871`. Each fact ends with a period. That is essentially all the Turtle you need to read.

**SPARQL** is the query language for RDF. If SQL is to relational tables, SPARQL is to triples. A simple SPARQL query looks like this:

```sparql
SELECT ?cert WHERE {
  msds:BATCH-2024-0871 msds:certificateNumber ?cert .
}
```

The `?cert` is a variable. The query reads: "find me every value of `?cert` such that the triple `(BATCH-2024-0871, certificateNumber, ?cert)` exists." Run that against our graph and you get back: "QC-CERT-44781".

If you can read this much SPARQL, you can read everything our system generates. We are going to lean on Gemini 2.5 Flash to generate more elaborate SPARQL on demand, but the patterns are always shaped like the example above.

> **Tip:** SPARQL has 4 query forms — `SELECT`, `CONSTRUCT`, `ASK`, `DESCRIBE`. We use only `SELECT` in this book. You will not miss the others.

---

## 4.3 Why HANA Cloud for the Knowledge Graph

SAP HANA Cloud has a built-in graph engine with native SPARQL support. This is architecturally significant for BTP deployments — and it is worth pausing to explain why we did not choose a dedicated triple store.

The alternatives are well-known: Apache Fuseki, AWS Neptune, GraphDB, Stardog. Each is a capable, purpose-built triple store with a standard SPARQL HTTP endpoint. The reason we do not use any of them is simple: we already have HANA Cloud running as our vector store. Adding a separate triple store means a second BTP service, a second set of credentials, a second Destination Service entry, and a second connection pool to manage in application code. For a production BTP deployment, that is unnecessary complexity.

HANA's SPARQL support is exposed through a single stored procedure: **`SPARQL_EXECUTE`**. This procedure runs SPARQL queries natively on the same database that holds vector embeddings. One HANA connection handles both `COSINE_SIMILARITY` searches on `MSDS_VECTORS` and SPARQL graph traversals on named RDF graphs. The application code in `vector_srv.py` and `kg_srv.py` both call `get_connection()` from the same `hdb_srv` module. No separate connection string, no separate service binding.

That is the entirety of the HANA SPARQL interface. There is no separate endpoint, no `/sparql` HTTP route. Every query, every insert, every drop — all of it goes through one procedure call:

```python
cursor.callproc("SPARQL_EXECUTE", (sparql_text, None, None, None))
```

The four arguments are: the SPARQL text, an optional `RDF_DATA` parameter for inline data, an optional `RDF_DATA_TYPE`, and an optional metadata flag. We pass `None` for all three optionals throughout this book.

The interesting part is the *result*. `callproc` returns a tuple of all four arguments after the procedure runs, with output values populated. The query results land in the **fourth element** of that tuple:

```python
result = cursor.callproc("SPARQL_EXECUTE", (sparql_query, None, None, None))
rows = result[3] if result and len(result) > 3 else []
```

Every result row is a tuple of column values, one per `?variable` in the `SELECT` clause. So a `SELECT ?value` returning three matches gives you something like:

```python
[("QC-CERT-44781",), ("ACME Steel AG",), ("Bureau Veritas Testing GmbH",)]
```

> **Important:** This is the single most useful sentence in this chapter. Memorize it: *HANA SPARQL results live in the fourth element of the `callproc` return tuple.* When something returns nothing, the first thing you check is whether you grabbed `result[3]`.

### Why a stored procedure and not an HTTP endpoint?

Because HANA already has secure, audited, governed connectivity through its SQL driver. Wrapping SPARQL inside a stored procedure means every SPARQL operation reuses the same authentication, the same connection pooling, the same transaction semantics, and the same logging that a normal SQL statement would. For an enterprise BTP deployment, that uniformity is more valuable than HTTP convenience. One Destination Service entry. One set of HANA credentials. Two retrieval strategies.

---

## 4.4 Designing the MSDS ontology — what facts matter?

Before writing any code we must decide what kinds of facts we care about. This decision is called **ontology design**, and it is the most important step of building a Knowledge Graph. The ontology becomes a constraint on what Gemini is allowed to extract — without it, the model invents predicates like `containsAt`, `madeOf`, `relatedTo`, and the graph turns into noise.

For a Batch Quality Certificate, the four predicates that matter for downstream queries are:

| Predicate | Domain | Range | Example |
|-----------|--------|-------|---------|
| `certifiedBy` | Batch | Supplier | BATCH-2024-0871 → ACME Steel AG |
| `testResult` | Batch | TestResult | BATCH-2024-0871 → PASS (tensile) |
| `certificateNumber` | Batch | CertNumber | BATCH-2024-0871 → QC-CERT-44781 |
| `certifyingLab` | Batch | Lab | BATCH-2024-0871 → Bureau Veritas Testing GmbH |

Four predicates. Four classes of node. That is enough to answer the precision questions our hybrid agent will face. If we needed material grade classifications across multiple test standards or transport classifications for logistics, we would extend the ontology. We deliberately stay small.

> **Note:** Real-world supply chain document systems track 50+ predicates — chemical compositions, mechanical test parameters, dimensional tolerances, surface treatment records, invoice line amounts. We pick four because they are enough to demonstrate the architecture and let you focus on the *patterns*. The patterns scale directly to broader ontologies.

---

## 4.5 The OWL ontology file — `MSDS_Ontology.ttl`

Create a file at the root of your project called `MSDS_Ontology.ttl`. Paste this:

```turtle
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix msds: <http://msds.knowledge-graph.org/ontology#> .

# Classes
msds:Material a owl:Class ;
    rdfs:label "Material" .

msds:Batch a owl:Class ;
    rdfs:label "Batch / Lot" .

msds:Supplier a owl:Class ;
    rdfs:label "Supplier" .

msds:TestResult a owl:Class ;
    rdfs:label "Test Result" .

msds:CertifyingLab a owl:Class ;
    rdfs:label "Certifying Laboratory" .

# Properties
msds:certifiedBy a owl:ObjectProperty ;
    rdfs:domain msds:Batch ;
    rdfs:range msds:Supplier ;
    rdfs:label "certified by" .

msds:testResult a owl:ObjectProperty ;
    rdfs:domain msds:Batch ;
    rdfs:range msds:TestResult ;
    rdfs:label "test result" .

msds:certificateNumber a owl:DatatypeProperty ;
    rdfs:domain msds:Batch ;
    rdfs:label "certificate number" .

msds:certifyingLab a owl:ObjectProperty ;
    rdfs:domain msds:Batch ;
    rdfs:range msds:CertifyingLab ;
    rdfs:label "certifying lab" .

msds:description a owl:DatatypeProperty ;
    rdfs:label "description" .
```

A few things to point out:

- **Classes** are categories of node. `msds:Batch`, `msds:Supplier`, `msds:CertifyingLab`, etc.
- **ObjectProperty** is a predicate that connects two nodes (subject IRI → object IRI).
- **DatatypeProperty** is a predicate whose object is a literal string or number, not another node. We use `msds:description` to hang the actual text value off a node.
- `rdfs:label` is human-readable text. It does not affect the graph; it just makes browsers and tools show better names.
- `rdfs:domain` and `rdfs:range` are the type constraints — domain is the type of the subject, range is the type of the object.

The namespace `http://msds.knowledge-graph.org/` reflects the MSDS reference implementation. For a production multi-document deployment serving multiple document types, the namespace would be organisation-specific — for example `http://materials.yourcompany.com/kg/`. The predicates are generic enough to describe facts across document types: `certifiedBy` works for any batch-to-supplier relationship; `testResult` works for any batch quality test outcome; `certifyingLab` works for laboratory accreditation records. The ontology names a domain, but the structural patterns transfer.

We are not loading this file into HANA at runtime. It is a contract — a documentation and prompting artifact. Our triple extractor reads this file (or a summary of it) to know what predicates Gemini is allowed to produce.

> **Tip:** If you ever need to share your ontology with another team or load it into a tool like Protégé for visual editing, this is the file you hand them. Keep it under version control alongside your code.

---

## 4.6 Extracting triples from MSDS text using Gemini

This is where the LLM earns its keep. We hand Gemini 2.5 Flash a chunk of document text and a list of allowed predicates, and ask it to return JSON triples. Three things make this trustworthy:

1. **Constrained predicates.** The prompt enumerates the four allowed predicates. Anything Gemini emits with a predicate outside that list is filtered out before it reaches HANA.
2. **JSON output.** No prose, no narration — just an array of objects. We strip any markdown fences Gemini sneaks in and `json.loads` the rest.
3. **Material number provided.** The subject of every triple is set externally. The model does not get to invent which batch the facts belong to.

This is an important architectural principle: Gemini 2.5 Flash acts as a structured extraction engine here, not as a data authority. The material number is injected by the CAP upload pipeline, validated against S/4HANA's API_PRODUCT_SRV before the document is accepted. Gemini extracts facts from text; it never decides which material those facts belong to.

Here is the prompt, lifted directly from `kg_srv.py`:

```python
prompt = f"""You are extracting structured facts from a Batch Quality Certificate document.

Extract facts ONLY using these relationship types:
- certifiedBy: batch → supplier name
- testResult: batch → test name and result (e.g. "tensile strength: 487 MPa, PASS")
- certificateNumber: batch → certificate number string
- certifyingLab: batch → certifying laboratory name

Material/Batch identifier: {material_number}

Return ONLY a JSON array of triples. Each triple must have:
- subject: the batch/material IRI
- predicate: the property name (certifiedBy, testResult, certificateNumber, certifyingLab)
- object: the value (string)

Example:
[
  {{"subject": "BATCH-2024-0871", "predicate": "certifiedBy", "object": "ACME Steel AG"}},
  {{"subject": "BATCH-2024-0871", "predicate": "certificateNumber", "object": "QC-CERT-44781"}},
  {{"subject": "BATCH-2024-0871", "predicate": "testResult", "object": "tensile strength: 487 MPa, PASS"}}
]

Document text to extract from:
{text[:3000]}

Return only the JSON array, no explanation."""
```

Notice the truncation `text[:3000]`. Batch certificates and quality documents can be 20+ pages. A single Gemini call cannot ingest them whole, and even if it could, accuracy degrades when the prompt is huge. In production we slice the document section-by-section (supplier header, test results table, certification footer, etc.). For this chapter we keep one call simple to focus on the mechanics.

> **Warning:** Never trust LLM JSON without parsing defensively. Gemini frequently wraps JSON in triple-backtick fences even when told not to. Strip those before `json.loads`.

The extractor returns a list of dictionaries:

```python
[
    {"subject": "BATCH-2024-0871", "predicate": "certifiedBy", "object": "ACME Steel AG"},
    {"subject": "BATCH-2024-0871", "predicate": "certificateNumber", "object": "QC-CERT-44781"},
    {"subject": "BATCH-2024-0871", "predicate": "testResult", "object": "tensile strength: 487 MPa, PASS"},
    {"subject": "BATCH-2024-0871", "predicate": "testResult", "object": "yield strength: 372 MPa, PASS"},
    {"subject": "BATCH-2024-0871", "predicate": "certifyingLab", "object": "Bureau Veritas Testing GmbH"}
]
```

Each row is one fact. Now we need a place to put them.

---

## 4.7 Storing triples in HANA — named graphs per material

Every triple in HANA's SPARQL engine lives in a **named graph**. A named graph is just an IRI that groups a set of triples. Think of it as a schema, but for facts instead of tables.

We follow a simple rule: **one named graph per material**. If we are storing facts about batch `BATCH-2024-0871`, every triple goes into the graph at IRI `http://msds.knowledge-graph.org/MSDS_Graph/BATCH-2024-0871`. If we are storing facts about `BATCH-2024-0992`, that material's triples go into a *different* graph IRI.

This pattern maps directly to SAP's material isolation requirements. In SAP MM, material data is scoped to a material number. In the Material Document Intelligence Platform, the same isolation holds: a SPARQL query scoped to the named graph for MAT-001 cannot return facts from MAT-002. The graph boundary enforces data isolation at the database level, not in application logic.

Three practical consequences:

1. **Clean deletion.** When a material is deprecated, `DROP GRAPH <graph-iri>` removes every fact for that material in one statement. There is no per-row cleanup, no orphans.
2. **Multi-tenant safety.** A bad extraction for one batch cannot pollute another batch's facts. Graph boundaries are enforced by HANA's SPARQL engine, not by application-layer filtering.
3. **Auditability.** A SPARQL query scoped to a single named graph can never read facts about other materials. When a compliance auditor asks "show me everything the system knows about batch X", the named graph provides a hard scope that the audit trail can reference.

The real graph URIs in the reference implementation follow the pattern `http://msds.knowledge-graph.org/MSDS_Graph/MAT-XXX`, where `MAT-XXX` is the SAP material or batch number validated at upload time. This is the same identifier stored in `MSDS_VECTORS.MATERIAL_NUMBER`. The named graph IRI and the vector table filter column are two representations of the same SAP material identifier.

Here is the storage code, the heart of `store_triples` in `kg_srv.py`:

```python
graph = graph_iri(material_number)              # the named-graph IRI
mat_iri = f"{GRAPH_BASE}/material/{material_number}"  # the material's node IRI
for triple in triples:
    predicate = triple.get("predicate", "")
    obj_value = str(triple.get("object", "")).replace("'", "\\'")
    obj_iri = f"{GRAPH_BASE}/{predicate}/{material_number}/{stored}"
    sparql_insert = f"""
        INSERT INTO GRAPH <{graph}> {{
            <{mat_iri}> <{ONTOLOGY_BASE}{predicate}> <{obj_iri}> .
            <{obj_iri}> <{ONTOLOGY_BASE}description> '{obj_value}' .
        }}
    """
    cursor.callproc("SPARQL_EXECUTE", (sparql_insert, None, None, None))
```

For each triple we insert *two* RDF statements:

1. The relationship: `material → predicate → blank-ish node`
2. The literal value on that node: `node → description → "ACME Steel AG"`

This two-step pattern is deliberate. It lets the same object node carry additional properties later — for instance we might want to add `certification_standard` or `accreditation_body` to a certifying lab node without restructuring the graph. Modeling values as nodes with `description` properties is more verbose than literal-only triples, but it pays off the moment you need to attach metadata.

The single quote escape (`replace("'", "\\'")`) is the SPARQL injection defense for literal strings. It is not as comprehensive as parameterized SQL, which is why we double up on validation upstream — see Section 5.9.

> **Note:** SPARQL Update syntax (`INSERT INTO GRAPH`) is part of the SPARQL 1.1 standard, not SPARQL 1.0. HANA supports it. Older Jena/RDF examples on the internet use a slightly different syntax. Stick with the form above.

---

## 4.8 Writing SPARQL queries — Gemini as the SPARQL translator

When a user asks "which supplier certified batch BATCH-2024-0871?", we cannot send that English directly to HANA. We must translate it to SPARQL.

Gemini 2.5 Flash acts as a SPARQL translator — the user asks in natural language, Gemini writes the SPARQL, HANA executes it. This is a key architectural pattern: the LLM never directly handles data — it only generates queries that the database executes. All data access goes through HANA's SPARQL engine. This is auditable, controllable, and secure. The data never leaves HANA to be processed by the LLM. Gemini sees the question and the schema; HANA owns the facts.

Two conditions make this work reliably. First, Gemini must know the available predicates and their full IRIs — without this, the model invents predicate names like `hazardClass` that do not exist in our graph. Second, Gemini must know the named graph IRI for this material — without the `GRAPH <iri> { ... }` wrapper, HANA returns zero rows silently.

Here is the heart of `query_graph`:

```python
sparql_prompt = f"""Generate a SPARQL SELECT query to answer this question about material {material_number}.

Available predicates:
- <{ONTOLOGY_BASE}certifiedBy> — links batch to supplier nodes
- <{ONTOLOGY_BASE}testResult> — links batch to test result nodes
- <{ONTOLOGY_BASE}certificateNumber> — links batch to certificate number nodes
- <{ONTOLOGY_BASE}certifyingLab> — links batch to certifying lab nodes
- <{ONTOLOGY_BASE}description> — literal value on any node

The material IRI is: <{mat_iri}>
The named graph is: <{graph}>

Question: {question}

Return ONLY the SPARQL query, wrapped in GRAPH clause like this:
SELECT ?value WHERE {{
  GRAPH <{graph}> {{
    <{mat_iri}> <predicate> ?node .
    ?node <{ONTOLOGY_BASE}description> ?value .
  }}
}}"""
```

The example query in the prompt is the **only SPARQL pattern** the rest of this book needs. Read it again. It does two hops:

1. From the batch node, follow some predicate to a supplier/lab/certificate node.
2. From that node, follow `description` to the literal text.

Two hops, one SELECT. That is the entire pattern.

> **Important:** The `GRAPH <iri> { ... }` wrapper is mandatory in HANA. Without it, HANA does not throw an error — it just returns zero rows. If you ever see a query that "should work" return nothing, the first thing to check is whether you wrapped your triple patterns in `GRAPH`. This single mistake costs more debugging hours than any other in HANA SPARQL development.

For the question "which supplier certified this batch?", Gemini emits something like:

```sparql
SELECT ?value WHERE {
  GRAPH <http://msds.knowledge-graph.org/MSDS_Graph/BATCH-2024-0871> {
    <http://msds.knowledge-graph.org/MSDS_Graph/material/BATCH-2024-0871>
        <http://msds.knowledge-graph.org/ontology#certifiedBy> ?node .
    ?node <http://msds.knowledge-graph.org/ontology#description> ?value .
  }
}
```

We pass it through `SPARQL_EXECUTE`, grab `result[3]`, and return `["ACME Steel AG"]`. Done.

The data stayed in HANA throughout. Gemini generated a query string; HANA executed it against the stored graph. The LLM never touched the supplier name directly.

---

## 4.9 Building `kg_srv.py` — the Knowledge Graph service layer

We collect everything into a single service module at `agents/srv/kg_srv.py`. It exposes five functions: `extract_triples`, `store_triples`, `query_graph`, `delete_graph`, `count_triples`. Create the file and paste this:

```python
import os
import re
import json
from .hdb_srv import get_connection
from .vertex_srv import get_llm

GRAPH_BASE = "http://msds.knowledge-graph.org/MSDS_Graph"
ONTOLOGY_BASE = "http://msds.knowledge-graph.org/ontology#"

MATERIAL_RE = re.compile(r"^[A-Za-z0-9_-]+$")

def _validate_material(material_number: str):
    if not MATERIAL_RE.match(material_number):
        raise ValueError(f"Invalid material number: {material_number}")

def graph_iri(material_number: str) -> str:
    _validate_material(material_number)
    return f"{GRAPH_BASE}/{material_number}"

def extract_triples(text: str, material_number: str) -> list[dict]:
    _validate_material(material_number)
    llm = get_llm()
    prompt = f"""You are extracting structured facts from a Batch Quality Certificate document.

Extract facts ONLY using these relationship types:
- certifiedBy: batch → supplier name
- testResult: batch → test name and result (e.g. "tensile strength: 487 MPa, PASS")
- certificateNumber: batch → certificate number string
- certifyingLab: batch → certifying laboratory name

Material/Batch identifier: {material_number}

Return ONLY a JSON array of triples. Each triple must have:
- subject: the batch/material IRI
- predicate: the property name (certifiedBy, testResult, certificateNumber, certifyingLab)  
- object: the value (string)

Example:
[
  {{"subject": "BATCH-2024-0871", "predicate": "certifiedBy", "object": "ACME Steel AG"}},
  {{"subject": "BATCH-2024-0871", "predicate": "certificateNumber", "object": "QC-CERT-44781"}},
  {{"subject": "BATCH-2024-0871", "predicate": "testResult", "object": "tensile strength: 487 MPa, PASS"}}
]

Document text to extract from:
{text[:3000]}

Return only the JSON array, no explanation."""

    response = llm.generate_content(prompt)
    raw = response.text.strip()
    # Strip markdown code blocks if present
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)
    return json.loads(raw)

def store_triples(material_number: str, triples: list[dict]):
    _validate_material(material_number)
    if not triples:
        return 0
    graph = graph_iri(material_number)
    mat_iri = f"{GRAPH_BASE}/material/{material_number}"
    conn = get_connection()
    cursor = conn.cursor()
    stored = 0
    for triple in triples:
        predicate = triple.get("predicate", "")
        obj_value = str(triple.get("object", "")).replace("'", "\\'")
        obj_iri = f"{GRAPH_BASE}/{predicate}/{material_number}/{stored}"
        sparql_insert = f"""
            INSERT INTO GRAPH <{graph}> {{
                <{mat_iri}> <{ONTOLOGY_BASE}{predicate}> <{obj_iri}> .
                <{obj_iri}> <{ONTOLOGY_BASE}description> '{obj_value}' .
            }}
        """
        try:
            cursor.callproc("SPARQL_EXECUTE", (sparql_insert, None, None, None))
            stored += 1
        except Exception as e:
            print(f"Warning: failed to store triple {triple}: {e}")
    conn.commit()
    cursor.close()
    return stored

def query_graph(material_number: str, question: str) -> dict:
    _validate_material(material_number)
    graph = graph_iri(material_number)
    mat_iri = f"{GRAPH_BASE}/material/{material_number}"
    llm = get_llm()

    # Generate SPARQL from the question
    sparql_prompt = f"""Generate a SPARQL SELECT query to answer this question about material {material_number}.

Available predicates:
- <{ONTOLOGY_BASE}certifiedBy> — links batch to supplier nodes
- <{ONTOLOGY_BASE}testResult> — links batch to test result nodes  
- <{ONTOLOGY_BASE}certificateNumber> — links batch to certificate number nodes
- <{ONTOLOGY_BASE}certifyingLab> — links batch to certifying lab nodes
- <{ONTOLOGY_BASE}description> — literal value on any node

The material IRI is: <{mat_iri}>
The named graph is: <{graph}>

Question: {question}

Return ONLY the SPARQL query, wrapped in GRAPH clause like this:
SELECT ?value WHERE {{
  GRAPH <{graph}> {{
    <{mat_iri}> <predicate> ?node .
    ?node <{ONTOLOGY_BASE}description> ?value .
  }}
}}"""

    sparql_response = llm.generate_content(sparql_prompt)
    sparql_query = sparql_response.text.strip()
    sparql_query = re.sub(r"```sparql\s*", "", sparql_query)
    sparql_query = re.sub(r"```\s*", "", sparql_query).strip()

    # Execute SPARQL
    conn = get_connection()
    cursor = conn.cursor()
    try:
        result = cursor.callproc("SPARQL_EXECUTE", (sparql_query, None, None, None))
        rows = result[3] if result and len(result) > 3 else []
        facts = [str(row[0]) for row in rows] if rows else []
    except Exception as e:
        facts = []
        sparql_query = f"Error: {e}"
    finally:
        cursor.close()

    return {
        "facts": facts,
        "sparql": sparql_query,
        "count": len(facts)
    }

def delete_graph(material_number: str) -> bool:
    _validate_material(material_number)
    graph = graph_iri(material_number)
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.callproc("SPARQL_EXECUTE", (f"DROP GRAPH <{graph}>", None, None, None))
        conn.commit()
        cursor.close()
        return True
    except Exception as e:
        cursor.close()
        print(f"Warning: could not delete graph {graph}: {e}")
        return False

def count_triples(material_number: str) -> int:
    _validate_material(material_number)
    graph = graph_iri(material_number)
    conn = get_connection()
    cursor = conn.cursor()
    try:
        result = cursor.callproc("SPARQL_EXECUTE", (
            f"SELECT (COUNT(*) AS ?count) WHERE {{ GRAPH <{graph}> {{ ?s ?p ?o }} }}",
            None, None, None
        ))
        rows = result[3] if result and len(result) > 3 else []
        cursor.close()
        return int(rows[0][0]) if rows else 0
    except Exception:
        cursor.close()
        return 0
```

### Validation: the KG equivalent of SQL injection

Take a close look at this regex:

```python
MATERIAL_RE = re.compile(r"^[A-Za-z0-9_-]+$")
```

It is enforced at the entry of every public function via `_validate_material`. Why is this so important?

The material number is **interpolated into IRIs** that we paste into SPARQL text. If someone calls `extract_triples(text, "../../admin")`, the resulting graph IRI becomes `http://msds.knowledge-graph.org/MSDS_Graph/../../admin`. Worse, a string like `> { ?s ?p ?o } DROP GRAPH <http://something` could close the IRI brackets and inject a destructive SPARQL update.

This is the SPARQL equivalent of SQL injection. The regex `^[A-Za-z0-9_-]+$` allows only letters, digits, underscore, and hyphen — characters that have no special meaning in SPARQL syntax. Any input containing slashes, spaces, angle brackets, quotes, or other SPARQL metacharacters is rejected before it can reach the query.

The same material number format is enforced in the CAP upload handler before the document reaches the Python layer at all, matching it against S/4HANA's product master. Validation at the CAP layer, at the Python service entry, and at the SQL parameter level — three checkpoints for a single identifier.

> **Warning:** If you change this regex to be more permissive — say, to allow forward slashes for hierarchical material codes — you must update the storage and query code to escape those characters too. The simplest defense is to keep the regex tight and document the constraint for upstream callers.

We also escape single quotes in literal values inside `store_triples`. Combined, validation on identifiers and escaping on literals cover the two injection vectors.

### What `delete_graph` and `count_triples` give us

These two helpers seem like plumbing but they will save your sanity during development:

- `count_triples(material_number)` — confirms data actually landed in HANA. Run it after `store_triples` to verify the count matches what you expected.
- `delete_graph(material_number)` — wipes a material's graph clean. Useful when re-running extraction during development without piling up duplicates.

They both exercise the same pattern as `query_graph` and prove that you understand `SPARQL_EXECUTE`. If you can write `count_triples`, you can write any read query.

---

## 4.10 Testing — store triples for a batch certificate, query for supplier and certificate number

Create `agents/test_kg.py`:

```python
import os
from dotenv import load_dotenv
from srv.kg_srv import extract_triples, store_triples, query_graph, count_triples

load_dotenv()

TEST_MATERIAL = "BATCH-2024-0871"
TEST_TEXT = """
Batch Quality Certificate

Material: Steel rod grade S355
Batch lot number: BATCH-2024-0871
Supplier: ACME Steel AG
Certificate number: QC-CERT-44781
Certification date: 2024-03-15

Test Results:
- Tensile strength: measured 487 MPa, specification minimum 355 MPa — PASS
- Yield strength: measured 372 MPa, specification minimum 345 MPa — PASS
- Elongation at break: measured 26%, specification minimum 22% — PASS

Certifying laboratory: Bureau Veritas Testing GmbH, Hamburg, Germany
Test standard: ISO 6892-1 (metallic materials tensile testing)
"""

print("Extracting triples from batch certificate text...")
triples = extract_triples(TEST_TEXT, TEST_MATERIAL)
print(f"Extracted {len(triples)} triples:")
for t in triples:
    print(f"  {t['predicate']}: {t['object']}")

print(f"\nStoring triples in HANA named graph...")
stored = store_triples(TEST_MATERIAL, triples)
print(f"Stored {stored} triples")

total = count_triples(TEST_MATERIAL)
print(f"Total triples in graph: {total}")

print("\nQuerying: 'Which supplier certified this batch?'")
result = query_graph(TEST_MATERIAL, "Which supplier certified this batch?")
print(f"SPARQL generated:\n{result['sparql']}")
print(f"Facts found: {result['facts']}")

print("\nQuerying: 'What is the certificate number?'")
result = query_graph(TEST_MATERIAL, "What is the certificate number?")
print(f"Facts found: {result['facts']}")
```

Run it from the `agents/` directory:

```bash
cd agents
python test_kg.py
```

Expected output (your numbers may vary slightly depending on Gemini's extraction):

```
Extracting triples from batch certificate text...
Extracted 5 triples:
  certifiedBy: ACME Steel AG
  certificateNumber: QC-CERT-44781
  testResult: tensile strength: 487 MPa, PASS
  testResult: yield strength: 372 MPa, PASS
  certifyingLab: Bureau Veritas Testing GmbH

Storing triples in HANA named graph...
Stored 5 triples
Total triples in graph: 10

Querying: 'Which supplier certified this batch?'
SPARQL generated:
SELECT ?value WHERE {
  GRAPH <http://msds.knowledge-graph.org/MSDS_Graph/BATCH-2024-0871> {
    <http://msds.knowledge-graph.org/MSDS_Graph/material/BATCH-2024-0871>
        <http://msds.knowledge-graph.org/ontology#certifiedBy> ?node .
    ?node <http://msds.knowledge-graph.org/ontology#description> ?value .
  }
}
Facts found: ['ACME Steel AG']

Querying: 'What is the certificate number?'
Facts found: ['QC-CERT-44781']
```

> **Note:** The total of 10 triples — twice the number of facts — is the two-statement pattern from Section 4.7. Each fact stores one `batch → predicate → node` edge plus one `node → description → literal` edge.

If your test prints `Facts found: []`, three things to check, in this order:

1. Did `store_triples` actually run before the query? Run `count_triples` and confirm the number is non-zero.
2. Is your generated SPARQL wrapped in `GRAPH <...>`? Print `result['sparql']` and inspect.
3. Did `result[3]` come back populated? Add a debug print right after `cursor.callproc` to confirm.

---

## 4.11 What the KG gets right that vector search cannot

Now the comparison promised since Chapter 3. Run the same question through both retrievers.

**Question:** "What is the certificate number for this batch?"

**Vector search** (Chapter 3):

```python
from srv.vector_srv import similarity_search
hits = similarity_search("What is the certificate number for this batch?", k=3)
for h in hits:
    print(f"score={h.score:.3f}  text={h.text[:120]}...")
```

Output:

```
score=0.651  text=Certificate number: QC-CERT-44781. Batch lot number: BATCH-2024-0871. Supplier: ACME Steel AG. Certification date: 2024...
score=0.602  text=Certifying laboratory: Bureau Veritas Testing GmbH, Hamburg, Germany. Test standard: ISO 6892-1...
score=0.578  text=Test Results — Tensile strength: measured 487 MPa, specification minimum 355 MPa — PASS...
```

The top hit *contains* the certificate number at score ~0.65. To produce the answer "QC-CERT-44781" you must hand the chunk to an LLM with another prompt: "extract the certificate number from this text". Two LLM calls, ~600ms each, fuzzy on the inputs and outputs, and you might miss it if the identifier appears in multiple contexts or if the scoring shifts on a different embedding model.

**Knowledge graph** (this chapter):

```python
result = query_graph("BATCH-2024-0871", "What is the certificate number?")
print(result['facts'])
```

Output:

```
['QC-CERT-44781']
```

One string. The exact identifier. No paragraph to parse, no scoring, no chunk boundary luck. The graph either has the fact or it does not — and if it has it, the query returns it. Gemini generated the SPARQL; HANA executed it; the facts came back directly. The LLM was a query generator, not a data processor.

The right answer to "What is the certificate number for batch BATCH-2024-0871?" is the exact string QC-CERT-44781 — not a paragraph, not a summary, not the surrounding context.

This is the contract:

| Vector store | Knowledge graph |
|--------------|-----------------|
| Returns text passages | Returns structured values |
| Ranks by similarity (0–1 score) | Returns exact matches (yes/no) |
| "How did the supplier describe the tensile test method?" | "What is the certificate number?" |
| Tolerates fuzzy phrasing | Demands precise predicate semantics |
| Best for methodology descriptions, inspection narratives | Best for identifiers, test results, dates, names |
| Failure mode: irrelevant chunk near top | Failure mode: empty result if predicate missing |

Neither one wins on its own. A user asking *"what does the certificate say about the test methodology used for tensile measurement?"* needs the prose chunk that paints the full picture. A user asking *"what is the certificate number?"* needs the identifier verbatim. The whole point of the next chapter — building the LangGraph supervisor — is to choose between them, or run both and merge the answers.

> **Tip:** A useful intuition: the vector store remembers *what was said*. The Knowledge Graph remembers *what is true*. The first is great for context, the second is great for facts. Most non-trivial enterprise document questions need both.

---

## 4.12 Summary

You now have a working Knowledge Graph layer on HANA Cloud. Specifically:

- An ontology (`MSDS_Ontology.ttl`) that defines four predicates (`certifiedBy`, `testResult`, `certificateNumber`, `certifyingLab`) and acts as a contract for what facts the system understands. The namespace `http://msds.knowledge-graph.org/` reflects the MSDS reference implementation; production deployments use an organisation-specific namespace.
- A `kg_srv.py` service module exposing `extract_triples`, `store_triples`, `query_graph`, `count_triples`, and `delete_graph`.
- A working pipeline that pulls JSON triples from document text using Gemini 2.5 Flash, stores them in per-material named graphs in HANA, and queries them with auto-generated SPARQL.
- Named graphs scoped per material or batch number, providing the same material isolation that SAP MM enforces for product master data. Graph `MSDS_Graph/BATCH-2024-0871` cannot return facts from `MSDS_Graph/BATCH-2024-0992`.
- Validated material identifiers and escaped literals — defense against the SPARQL equivalent of injection.
- The pattern `cursor.callproc("SPARQL_EXECUTE", (query, None, None, None))` followed by `result[3]` for rows.
- The mandatory `GRAPH <iri> { ... }` wrapper for every triple pattern.
- No separate triple store required. One HANA Cloud instance, accessed through one connection pool, serves both vector embeddings and RDF graph traversals.

The investment was small — under 200 lines of Python, one Turtle file, and a single stored procedure call — but the capability is fundamentally different from what vector search alone gave us. We can now answer fact-shaped questions with fact-shaped answers. And we can do it without adding a second BTP service or a second set of credentials.

---

## 4.13 Checkpoint

Before moving to Chapter 5, confirm the following from the `agents/` directory:

```bash
python -c "from srv.kg_srv import count_triples; print(count_triples('BATCH-2024-0871'))"
```

This should print a number greater than zero — the count of triples currently stored for the test batch.

```bash
python -c "from srv.kg_srv import query_graph; print(query_graph('BATCH-2024-0871', 'Which supplier certified this batch?')['facts'])"
```

This should print a list containing `ACME Steel AG`.

If both succeed, you have:

- HANA Cloud reachable through `hdb_srv`
- Gemini 2.5 Flash generating valid SPARQL through the `get_llm()` getter in `vertex_srv`
- A populated named graph for `BATCH-2024-0871` at `http://msds.knowledge-graph.org/MSDS_Graph/BATCH-2024-0871`
- Working extraction, storage, and query paths

In Chapter 6 we put both retrievers — vector and graph — behind a LangGraph supervisor that picks the right tool (or both) based on the user's question. The hybrid in *Hybrid RAG* finally starts to make sense.
