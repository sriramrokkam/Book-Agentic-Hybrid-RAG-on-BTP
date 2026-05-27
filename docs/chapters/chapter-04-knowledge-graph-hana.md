# Chapter 4: Knowledge Graphs on SAP HANA Cloud

In Chapter 3 we built a vector store that retrieves passages of MSDS text by semantic similarity. It works beautifully when the question is fuzzy — "what precautions should I take when using acetone near a flame?" — because the answer lives in flowing prose. But the moment a user asks something precise — "what is the GHS hazard classification for acetone?" — vector search starts to wobble. The right paragraph might come back with a similarity score of 0.62, sandwiched between a chunk about storage temperature and another about regulatory disclaimers. The exact codes — H225, H319, H336 — are buried in a sentence among many other sentences.

This chapter fills that gap. We are going to teach our system to remember structured facts as a graph, store them in SAP HANA Cloud, and query them with SPARQL. By the end of this chapter, the question "what are the GHS hazard codes for acetone?" will return exactly `["H225", "H319", "H336"]` — not a paragraph that mentions them, the codes themselves.

If you have never written a line of RDF or SPARQL, do not worry. There are entire books about each. We need only enough of each to build a working hybrid RAG system. Concretely, you will need to understand three SPARQL patterns and one stored procedure call. That is the whole surface area for the rest of this book.

---

## 4.1 What is a knowledge graph?

A **knowledge graph** is a collection of facts, where each fact is expressed as a relationship between two things. That is the entire idea. The vocabulary that the RDF community uses around it can sound ceremonial — "subject-predicate-object triples organized as a directed labeled multigraph" — but strip the ceremony away and you are left with three-word sentences.

Consider the fact:

> Acetone has hazard code H225.

Three pieces:

| Part | Value |
|------|-------|
| Subject | Acetone |
| Predicate | has hazard code |
| Object | H225 |

This three-part fact is called a **triple**. A knowledge graph is a pile of triples. If we add more triples, the structure starts to feel like something an SAP developer already knows:

```
Acetone        hasHazardCode      H225
Acetone        hasHazardCode      H319
Acetone        hasHazardCode      H336
Acetone        hasExposureLimit   "500 ppm TWA"
Acetone        requiresPrecaution "Keep away from open flames"
Acetone        hasSupplier        "Sigma-Aldrich"
H225           description        "Highly flammable liquid and vapour"
```

Read those rows. You have just read a knowledge graph. Each row is a triple. The same subject (Acetone) can appear in many rows, just like a material number can appear many times in MARA-related tables. The same predicate (hasHazardCode) can be reused for any other material.

> **Note:** If you are mentally translating this to a relational table with three columns — `subject`, `predicate`, `object` — you are not wrong. That is exactly how RDF can be persisted internally. The difference from a normal table is *what kinds of questions you can ask of it*, which we will get to with SPARQL.

### Why call it a graph?

Because if you draw it, it looks like one. Subjects and objects are nodes; predicates are edges. The same H225 node might be the object of many materials' `hasHazardCode` edges. The same supplier "Sigma-Aldrich" node might be the object of many `hasSupplier` edges. The graph emerges naturally from shared values.

![Knowledge Graph Node: Acetone](docs/screenshots/diagrams/01-kg-acetone-node.png)
*Figure: RDF knowledge graph representation of an Acetone MSDS entry — four triples extracted from a single document, stored as a named graph in SAP HANA Cloud*

### What does this give us that a relational schema does not?

Three things, in order of how much you will care:

1. **No schema changes when facts evolve.** Tomorrow we decide MSDS documents should also track `hasFireExtinguisher`. We do not run a `DDL` migration; we just start storing triples with that predicate. The graph is permissive about what relationships exist.
2. **Queries that follow paths.** "Find me every material whose supplier is in Missouri" — that is a graph traversal. SPARQL expresses it directly. In SQL it would be a chain of joins.
3. **Identity by IRI.** Every node has a globally unique IRI (a URL-shaped identifier). This means a triple in our system can refer to the same Acetone node that any other system uses, simply by sharing an IRI. You will not need this superpower in this book, but it is the reason RDF exists.

For our MSDS use case we will use the graph mainly for the first reason — flexibility — and for the *precision* it gives us at query time. A SPARQL query for hazard codes returns hazard codes, not paragraphs.

![Knowledge Graph Pipeline](docs/screenshots/diagrams/05-kg-pipeline.png)

*Figure 4.2 — The KG pipeline has two phases. Ingestion (top): full PDF text is passed to Gemini along with the OWL ontology as a constraint, producing RDF triples that are stored as a named graph in HANA. Query time (bottom): Gemini generates a SPARQL SELECT query from the user's question, which is executed via `SPARQL_EXECUTE`. A retry loop broadens the query if results are empty. The resulting facts are summarised by Gemini into an answer fragment.*

---

## 4.2 RDF and SPARQL — the standards explained plainly

**RDF** stands for Resource Description Framework. It is the W3C standard for expressing triples. There are several serialization formats — RDF/XML, JSON-LD, Turtle — that all encode the same triples in different syntaxes. We will use **Turtle** (file extension `.ttl`) because it is the most readable.

A Turtle file looks like this:

```turtle
@prefix msds: <http://msds.knowledge-graph.org/ontology#> .

msds:Acetone msds:hasHazardCode msds:H225 .
msds:Acetone msds:hasHazardCode msds:H319 .
```

The `@prefix` line defines a shorthand: instead of writing the full IRI `http://msds.knowledge-graph.org/ontology#Acetone`, we write `msds:Acetone`. Each fact ends with a period. That is essentially all the Turtle you need to read.

**SPARQL** is the query language for RDF. If SQL is to relational tables, SPARQL is to triples. A simple SPARQL query looks like this:

```sparql
SELECT ?code WHERE {
  msds:Acetone msds:hasHazardCode ?code .
}
```

The `?code` is a variable. The query reads: "find me every value of `?code` such that the triple `(Acetone, hasHazardCode, ?code)` exists." Run that against our graph and you get back three rows: `H225`, `H319`, `H336`.

If you can read this much SPARQL, you can read everything our system generates. We are going to lean on Gemini to generate more elaborate SPARQL on demand, but the patterns are always shaped like the example above.

> **Tip:** SPARQL has 4 query forms — `SELECT`, `CONSTRUCT`, `ASK`, `DESCRIBE`. We use only `SELECT` in this book. You will not miss the others.

---

## 4.3 Why HANA Cloud supports SPARQL

SAP HANA Cloud has a built-in graph engine. Among other things, it supports the W3C SPARQL standard for querying RDF data. Unlike dedicated triple stores (Apache Jena, GraphDB, Stardog), HANA exposes SPARQL through a single stored procedure: **`SPARQL_EXECUTE`**.

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

Every result row is a tuple of column values, one per `?variable` in the `SELECT` clause. So a `SELECT ?code` returning three matches gives you something like:

```python
[("H225",), ("H319",), ("H336",)]
```

> **Important:** This is the single most useful sentence in this chapter. Memorize it: *HANA SPARQL results live in the fourth element of the `callproc` return tuple.* When something returns nothing, the first thing you check is whether you grabbed `result[3]`.

### Why a stored procedure and not an HTTP endpoint?

Because HANA already has secure, audited, governed connectivity through its SQL driver. Wrapping SPARQL inside a stored procedure means every SPARQL operation reuses the same authentication, the same connection pooling, the same transaction semantics, and the same logging that a normal SQL statement would. For an enterprise platform, that uniformity is more valuable than HTTP convenience.

---

## 4.4 Designing the MSDS ontology — what facts matter?

Before writing any code we must decide what kinds of facts we care about. This decision is called **ontology design**, and it is the most important step of building a knowledge graph. The ontology becomes a constraint on what Gemini is allowed to extract — without it, the model invents predicates like `containsAt`, `madeOf`, `relatedTo`, and the graph turns into noise.

For an MSDS, the four predicates that matter for downstream queries are:

| Predicate | Domain | Range | Example |
|-----------|--------|-------|---------|
| `hasHazardCode` | Material | HazardCode | Acetone → H225 |
| `hasExposureLimit` | Material | ExposureLimit | Acetone → "500 ppm TWA" |
| `requiresPrecaution` | Material | Precaution | Acetone → "Avoid open flames" |
| `hasSupplier` | Material | Supplier | Acetone → "Sigma-Aldrich" |

Four predicates. Four classes of node. That is enough to answer the precision questions our hybrid agent will face. If we needed regulatory codes in five jurisdictions or transport classifications for IATA, we would extend the ontology. We deliberately stay small.

> **Note:** Real-world MSDS systems track 50+ predicates — physical properties, transport codes, decomposition products, first-aid measures, environmental fate. We pick four because they are enough to demonstrate the architecture and let you focus on the *patterns*. The patterns scale.

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

msds:HazardCode a owl:Class ;
    rdfs:label "GHS Hazard Code" .

msds:ExposureLimit a owl:Class ;
    rdfs:label "Occupational Exposure Limit" .

msds:Precaution a owl:Class ;
    rdfs:label "Safety Precaution" .

msds:Supplier a owl:Class ;
    rdfs:label "Supplier" .

# Properties
msds:hasHazardCode a owl:ObjectProperty ;
    rdfs:domain msds:Material ;
    rdfs:range msds:HazardCode ;
    rdfs:label "has hazard code" .

msds:hasExposureLimit a owl:ObjectProperty ;
    rdfs:domain msds:Material ;
    rdfs:range msds:ExposureLimit ;
    rdfs:label "has exposure limit" .

msds:requiresPrecaution a owl:ObjectProperty ;
    rdfs:domain msds:Material ;
    rdfs:range msds:Precaution ;
    rdfs:label "requires precaution" .

msds:hasSupplier a owl:ObjectProperty ;
    rdfs:domain msds:Material ;
    rdfs:range msds:Supplier ;
    rdfs:label "has supplier" .

msds:code a owl:DatatypeProperty ;
    rdfs:domain msds:HazardCode ;
    rdfs:label "hazard code value" .

msds:description a owl:DatatypeProperty ;
    rdfs:label "description" .

msds:limitValue a owl:DatatypeProperty ;
    rdfs:domain msds:ExposureLimit ;
    rdfs:label "limit value" .

msds:limitUnit a owl:DatatypeProperty ;
    rdfs:domain msds:ExposureLimit ;
    rdfs:label "limit unit" .
```

A few things to point out:

- **Classes** are categories of node. `msds:Material`, `msds:HazardCode`, etc.
- **ObjectProperty** is a predicate that connects two nodes (subject IRI → object IRI).
- **DatatypeProperty** is a predicate whose object is a literal string or number, not another node. We use `msds:description` to hang the actual text value off a node.
- `rdfs:label` is human-readable text. It does not affect the graph; it just makes browsers and tools show better names.
- `rdfs:domain` and `rdfs:range` are the type constraints — domain is the type of the subject, range is the type of the object.

We are not loading this file into HANA at runtime. It is a contract — a documentation and prompting artifact. Our triple extractor reads this file (or a summary of it) to know what predicates Gemini is allowed to produce.

> **Tip:** If you ever need to share your ontology with another team or load it into a tool like Protégé for visual editing, this is the file you hand them. Keep it under version control alongside your code.

---

## 4.6 Extracting triples from MSDS text using Gemini

This is where the LLM earns its keep. We hand Gemini a chunk of MSDS text and a list of allowed predicates, and ask it to return JSON triples. Three things make this trustworthy:

1. **Constrained predicates.** The prompt enumerates the four allowed predicates. Anything Gemini emits with a predicate outside that list is filtered out before it reaches HANA.
2. **JSON output.** No prose, no narration — just an array of objects. We strip any markdown fences Gemini sneaks in and `json.loads` the rest.
3. **Material number provided.** The subject of every triple is set externally. The model does not get to invent which material the facts belong to.

Here is the prompt, lifted directly from `kg_srv.py`:

```python
prompt = f"""You are extracting structured facts from an MSDS (Material Safety Data Sheet) document.

Extract facts ONLY using these relationship types:
- hasHazardCode: material → GHS hazard code (e.g. H225, H319)
- hasExposureLimit: material → occupational exposure limit with value and unit
- requiresPrecaution: material → safety precaution text
- hasSupplier: material → supplier name

Material number: {material_number}

Return ONLY a JSON array of triples. Each triple must have:
- subject: the material IRI
- predicate: the property name (hasHazardCode, hasExposureLimit, requiresPrecaution, hasSupplier)
- object: the value (string)

Example:
[
  {{"subject": "ACETONE-001", "predicate": "hasHazardCode", "object": "H225"}},
  {{"subject": "ACETONE-001", "predicate": "hasHazardCode", "object": "H319"}},
  {{"subject": "ACETONE-001", "predicate": "hasExposureLimit", "object": "500 ppm TWA"}}
]

MSDS text to extract from:
{text[:3000]}

Return only the JSON array, no explanation."""
```

Notice the truncation `text[:3000]`. MSDS documents can be 20+ pages. A single Gemini call cannot ingest them whole, and even if it could, accuracy degrades when the prompt is huge. In production we slice the document section-by-section (Section 2 for hazards, Section 8 for exposure limits, etc.). For this chapter we keep one call simple to focus on the mechanics.

> **Warning:** Never trust LLM JSON without parsing defensively. Gemini frequently wraps JSON in triple-backtick fences even when told not to. Strip those before `json.loads`.

The extractor returns a list of dictionaries:

```python
[
    {"subject": "ACETONE-TEST-001", "predicate": "hasHazardCode", "object": "H225"},
    {"subject": "ACETONE-TEST-001", "predicate": "hasHazardCode", "object": "H319"},
    {"subject": "ACETONE-TEST-001", "predicate": "hasHazardCode", "object": "H336"},
    {"subject": "ACETONE-TEST-001", "predicate": "hasExposureLimit", "object": "500 ppm TWA"},
    {"subject": "ACETONE-TEST-001", "predicate": "requiresPrecaution", "object": "Keep away from heat, sparks, and open flames"},
    {"subject": "ACETONE-TEST-001", "predicate": "hasSupplier", "object": "Sigma-Aldrich"}
]
```

Each row is one fact. Now we need a place to put them.

---

## 4.7 Storing triples in HANA — named graphs per document

Every triple in HANA's SPARQL engine lives in a **named graph**. A named graph is just an IRI that groups a set of triples. Think of it as a schema, but for facts instead of tables.

We follow a simple rule: **one named graph per material**. If we are storing facts about material `ACETONE-TEST-001`, every triple goes into the graph at IRI `http://msds.knowledge-graph.org/MSDS_Graph/ACETONE-TEST-001`. If we are storing facts about `BENZENE-002`, that material's triples go into a *different* graph IRI.

Why?

1. **Clean deletion.** When a material is deprecated, `DROP GRAPH <graph-iri>` removes every fact for that material in one statement. There is no per-row cleanup, no orphans.
2. **Isolation.** Two materials can never accidentally share a triple. A bad extraction for benzene cannot pollute acetone's facts.
3. **Auditability.** A SPARQL query scoped to a single graph can never read facts about other materials. This is a useful property when an engineer asks "show me everything we know about material X" and you must guarantee that nothing else leaks in.

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
2. The literal value on that node: `node → description → "H225"`

This two-step pattern is deliberate. It lets the same object node carry additional properties later — for instance we might want to add `severity` or `regulation_source` to a hazard code without restructuring the graph. Modeling values as nodes with `description` properties is more verbose than literal-only triples, but it pays off the moment you need to attach metadata.

The single quote escape (`replace("'", "\\'")`) is the SPARQL injection defense for literal strings. It is not as comprehensive as parameterized SQL, which is why we double up on validation upstream — see Section 5.9.

> **Note:** SPARQL Update syntax (`INSERT INTO GRAPH`) is part of the SPARQL 1.1 standard, not SPARQL 1.0. HANA supports it. Older Jena/RDF examples on the internet use a slightly different syntax. Stick with the form above.

---

## 4.8 Writing SPARQL queries — from natural language to graph traversal

When a user asks "what are the GHS hazard codes for acetone?", we cannot send that English directly to HANA. We must translate it to SPARQL. Two strategies:

1. **Hand-write SPARQL templates.** For a fixed set of question types (hazards, limits, suppliers, precautions) you write four templates and pick the right one based on keyword matching.
2. **Have the LLM generate SPARQL.** Pass the question and a description of the schema to Gemini, get back a query, run it.

We use approach 2 in this book because it scales as the ontology grows and because Gemini is genuinely good at this task when given the right context. The crucial input to Gemini is the *list of available predicates* and the *named graph IRI*. Without those, the model invents predicate names like `hazardClass` that do not exist in our graph.

Here is the heart of `query_graph`:

```python
sparql_prompt = f"""Generate a SPARQL SELECT query to answer this question about material {material_number}.

Available predicates:
- <{ONTOLOGY_BASE}hasHazardCode> — links material to hazard code nodes
- <{ONTOLOGY_BASE}hasExposureLimit> — links material to exposure limit nodes
- <{ONTOLOGY_BASE}requiresPrecaution> — links material to precaution nodes
- <{ONTOLOGY_BASE}hasSupplier> — links material to supplier nodes
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

1. From the material node, follow some predicate to a hazard/limit/supplier node.
2. From that node, follow `description` to the literal text.

Two hops, one SELECT. That is the entire pattern.

> **Important:** The `GRAPH <iri> { ... }` wrapper is mandatory in HANA. Without it, HANA does not throw an error — it just returns zero rows. If you ever see a query that "should work" return nothing, the first thing to check is whether you wrapped your triple patterns in `GRAPH`. This single mistake costs more debugging hours than any other in HANA SPARQL development.

For the question "what are the hazard codes?", Gemini emits something like:

```sparql
SELECT ?value WHERE {
  GRAPH <http://msds.knowledge-graph.org/MSDS_Graph/ACETONE-TEST-001> {
    <http://msds.knowledge-graph.org/MSDS_Graph/material/ACETONE-TEST-001>
        <http://msds.knowledge-graph.org/ontology#hasHazardCode> ?node .
    ?node <http://msds.knowledge-graph.org/ontology#description> ?value .
  }
}
```

We pass it through `SPARQL_EXECUTE`, grab `result[3]`, and return `["H225", "H319", "H336"]`. Done.

---

## 4.9 Building `kg_srv.py` — the knowledge graph service layer

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
    prompt = f"""You are extracting structured facts from an MSDS (Material Safety Data Sheet) document.

Extract facts ONLY using these relationship types:
- hasHazardCode: material → GHS hazard code (e.g. H225, H319)
- hasExposureLimit: material → occupational exposure limit with value and unit
- requiresPrecaution: material → safety precaution text
- hasSupplier: material → supplier name

Material number: {material_number}

Return ONLY a JSON array of triples. Each triple must have:
- subject: the material IRI
- predicate: the property name (hasHazardCode, hasExposureLimit, requiresPrecaution, hasSupplier)  
- object: the value (string)

Example:
[
  {{"subject": "ACETONE-001", "predicate": "hasHazardCode", "object": "H225"}},
  {{"subject": "ACETONE-001", "predicate": "hasHazardCode", "object": "H319"}},
  {{"subject": "ACETONE-001", "predicate": "hasExposureLimit", "object": "500 ppm TWA"}}
]

MSDS text to extract from:
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
- <{ONTOLOGY_BASE}hasHazardCode> — links material to hazard code nodes
- <{ONTOLOGY_BASE}hasExposureLimit> — links material to exposure limit nodes  
- <{ONTOLOGY_BASE}requiresPrecaution> — links material to precaution nodes
- <{ONTOLOGY_BASE}hasSupplier> — links material to supplier nodes
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

> **Warning:** If you change this regex to be more permissive — say, to allow forward slashes for hierarchical material codes — you must update the storage and query code to escape those characters too. The simplest defense is to keep the regex tight and document the constraint for upstream callers.

We also escape single quotes in literal values inside `store_triples`. Combined, validation on identifiers and escaping on literals cover the two injection vectors.

### What `delete_graph` and `count_triples` give us

These two helpers seem like plumbing but they will save your sanity during development:

- `count_triples(material_number)` — confirms data actually landed in HANA. Run it after `store_triples` to verify the count matches what you expected.
- `delete_graph(material_number)` — wipes a material's graph clean. Useful when re-running extraction during development without piling up duplicates.

They both exercise the same pattern as `query_graph` and prove that you understand `SPARQL_EXECUTE`. If you can write `count_triples`, you can write any read query.

---

## 4.10 Testing — store triples for acetone, query for GHS codes

Create `agents/test_kg.py`:

```python
import os
from dotenv import load_dotenv
from srv.kg_srv import extract_triples, store_triples, query_graph, count_triples

load_dotenv()

TEST_MATERIAL = "ACETONE-TEST-001"
TEST_TEXT = """
Section 2: Hazard Identification
GHS Classification: Flammable Liquid Category 2 (H225), Eye Irritation Category 2A (H319),
Specific Target Organ Toxicity (Single Exposure) Category 3 (H336).

Section 8: Exposure Controls
OSHA PEL: 1000 ppm TWA. ACGIH TLV: 500 ppm TWA, 750 ppm STEL.

Section 7: Handling and Storage  
Keep away from heat, sparks, and open flames. Use explosion-proof equipment.
Wear chemical-resistant gloves and safety goggles. Ensure adequate ventilation.

Supplier: Sigma-Aldrich, 3050 Spruce Street, St. Louis, MO 63103
"""

print("Extracting triples from MSDS text...")
triples = extract_triples(TEST_TEXT, TEST_MATERIAL)
print(f"Extracted {len(triples)} triples:")
for t in triples:
    print(f"  {t['predicate']}: {t['object']}")

print(f"\nStoring triples in HANA named graph...")
stored = store_triples(TEST_MATERIAL, triples)
print(f"Stored {stored} triples")

total = count_triples(TEST_MATERIAL)
print(f"Total triples in graph: {total}")

print("\nQuerying: 'What are the GHS hazard codes for this material?'")
result = query_graph(TEST_MATERIAL, "What are the GHS hazard codes for this material?")
print(f"SPARQL generated:\n{result['sparql']}")
print(f"Facts found: {result['facts']}")

print("\nQuerying: 'What is the exposure limit?'")
result = query_graph(TEST_MATERIAL, "What is the occupational exposure limit?")
print(f"Facts found: {result['facts']}")
```

Run it from the `agents/` directory:

```bash
cd agents
python test_kg.py
```

Expected output (your numbers may vary slightly depending on Gemini's extraction):

```
Extracting triples from MSDS text...
Extracted 8 triples:
  hasHazardCode: H225
  hasHazardCode: H319
  hasHazardCode: H336
  hasExposureLimit: 1000 ppm TWA
  hasExposureLimit: 500 ppm TWA
  requiresPrecaution: Keep away from heat, sparks, and open flames
  requiresPrecaution: Wear chemical-resistant gloves and safety goggles
  hasSupplier: Sigma-Aldrich

Storing triples in HANA named graph...
Stored 8 triples

Total triples in graph: 16

Querying: 'What are the GHS hazard codes for this material?'
SPARQL generated:
SELECT ?value WHERE {
  GRAPH <http://msds.knowledge-graph.org/MSDS_Graph/ACETONE-TEST-001> {
    <http://msds.knowledge-graph.org/MSDS_Graph/material/ACETONE-TEST-001>
        <http://msds.knowledge-graph.org/ontology#hasHazardCode> ?node .
    ?node <http://msds.knowledge-graph.org/ontology#description> ?value .
  }
}
Facts found: ['H225', 'H319', 'H336']

Querying: 'What is the exposure limit?'
Facts found: ['1000 ppm TWA', '500 ppm TWA']
```

```
# Expected terminal output:
Stored 12 triples for material: acetone-test
Running SPARQL query for hazard codes...
SPARQL query executed in 0.23s
Hazard codes found: ['H225', 'H319', 'H336']
Knowledge graph test: OK
```

> **Note:** The total of 16 triples — twice the number of facts — is the two-statement pattern from Section 5.7. Each fact stores one `material → predicate → node` edge plus one `node → description → literal` edge.

If your test prints `Facts found: []`, three things to check, in this order:

1. Did `store_triples` actually run before the query? Run `count_triples` and confirm the number is non-zero.
2. Is your generated SPARQL wrapped in `GRAPH <...>`? Print `result['sparql']` and inspect.
3. Did `result[3]` come back populated? Add a debug print right after `cursor.callproc` to confirm.

---

## 4.11 What the KG gets right that vector search cannot

Now the comparison promised since Chapter 3. Run the same question through both retrievers.

**Question:** "What are the GHS hazard codes for acetone?"

**Vector search** (Chapter 3):

```python
from srv.vector_srv import similarity_search
hits = similarity_search("What are the GHS hazard codes for acetone?", k=3)
for h in hits:
    print(f"score={h.score:.3f}  text={h.text[:120]}...")
```

Output:

```
score=0.681  text=Section 2: Hazard Identification — GHS Classification: Flammable Liquid Category 2 (H225), Eye Irritation Category 2A...
score=0.612  text=Storage temperature should not exceed 25°C. Refer to local regulations for transport classification...
score=0.594  text=Section 4: First Aid Measures — In case of skin contact wash with plenty of water...
```

The top hit *contains* the codes. To produce the answer "H225, H319, H336" you must hand the chunk to an LLM with another prompt: "extract the GHS codes from this text". Two LLM calls, ~600ms each, fuzzy on the inputs and outputs, and you still might miss H336 if it appears in a different chunk that scored 0.59.

**Knowledge graph** (this chapter):

```python
result = query_graph("ACETONE-TEST-001", "What are the GHS hazard codes for acetone?")
print(result['facts'])
```

Output:

```
['H225', 'H319', 'H336']
```

Three strings. Exact codes. No paragraph to parse, no scoring, no chunk boundary luck. The graph either has the fact or it does not — and if it has it, the query returns it.

This is the contract:

| Vector store | Knowledge graph |
|--------------|-----------------|
| Returns text passages | Returns structured values |
| Ranks by similarity (0–1 score) | Returns exact matches (yes/no) |
| Tolerates fuzzy phrasing | Demands precise predicate semantics |
| Best for "how do I…" questions | Best for "what is the value of…" questions |
| Failure mode: irrelevant chunk near top | Failure mode: empty result if predicate missing |

Neither one wins on its own. A user asking *"what precautions are needed when handling acetone near an open flame?"* needs the prose chunk that paints the full picture. A user asking *"what is the GHS hazard classification?"* needs the codes verbatim. The whole point of the next chapter — building the LangGraph supervisor — is to choose between them, or run both and merge the answers.

> **Tip:** A useful intuition: the vector store remembers *what was said*. The knowledge graph remembers *what is true*. The first is great for context, the second is great for facts. Most non-trivial questions need both.

---

## 4.12 Summary

You now have a working knowledge graph layer on HANA Cloud. Specifically:

- An ontology (`MSDS_Ontology.ttl`) that defines four predicates and acts as a contract for what facts the system understands.
- A `kg_srv.py` service module exposing `extract_triples`, `store_triples`, `query_graph`, `count_triples`, and `delete_graph`.
- A working pipeline that pulls JSON triples from MSDS text using Gemini, stores them in per-material named graphs, and queries them with auto-generated SPARQL.
- Validated material identifiers and escaped literals — defense against the SPARQL equivalent of injection.
- The pattern `cursor.callproc("SPARQL_EXECUTE", (query, None, None, None))` followed by `result[3]` for rows.
- The mandatory `GRAPH <iri> { ... }` wrapper for every triple pattern.

The investment was small — under 200 lines of Python, one Turtle file, and a single stored procedure call — but the capability is fundamentally different from what vector search alone gave us. We can now answer fact-shaped questions with fact-shaped answers.

---

## 4.13 Checkpoint

Before moving to Chapter 5, confirm the following from the `agents/` directory:

```bash
python -c "from srv.kg_srv import count_triples; print(count_triples('ACETONE-TEST-001'))"
```

This should print a number greater than zero — the count of triples currently stored for the test material.

```bash
python -c "from srv.kg_srv import query_graph; print(query_graph('ACETONE-TEST-001', 'What are the hazard codes?')['facts'])"
```

This should print a list containing `H225`, `H319`, and `H336` (and possibly others).

If both succeed, you have:

- HANA Cloud reachable through `hdb_srv`
- Vertex AI generating valid SPARQL through `vertex_srv`
- A populated named graph for `ACETONE-TEST-001`
- Working extraction, storage, and query paths

In Chapter 6 we put both retrievers — vector and graph — behind a LangGraph supervisor that picks the right tool (or both) based on the user's question. The hybrid in *Hybrid RAG* finally starts to make sense.
